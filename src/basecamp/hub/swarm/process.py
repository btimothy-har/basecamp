"""Subprocess lifecycle helpers for daemon-dispatched agents."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from ..frames import DispatchSpec
from ..registry import Registry
from ..store import Store
from .run_result import load_run_result, run_result_path

ProcessExitHook = Callable[[str], Awaitable[None]]
RUNNER_MODULE = "basecamp.hub.swarm.runner"
# Also match the pre-rename module so a legacy `basecamp swarm daemon`'s orphaned
# runners stay reapable across the rename (mirrors the TS reaper's old-or-new
# command match); drop the legacy entry a release later.
_RUNNER_MODULE_MATCHES = (RUNNER_MODULE, "basecamp.swarm.runner")


def build_runner_argv(
    *,
    result_path: str | Path,
    spec: DispatchSpec,
    fork_source_path: str | None,
) -> list[str]:
    fork_part = ["--fork", fork_source_path] if fork_source_path is not None else []
    return [
        sys.executable,
        "-m",
        RUNNER_MODULE,
        "--result-path",
        str(result_path),
        "--",
        *spec.argv,
        *fork_part,
        spec.task,
    ]


def build_child_env(
    *,
    spec_env: dict[str, str],
    daemon_socket_path: str,
    run_id: str,
    report_token: str,
    agent_id: str,
    dispatcher_node_id: str,
    child_depth: int,
    agent_handle: str | None,
) -> dict[str, str]:
    child_env = {
        **spec_env,
        "BASECAMP_DAEMON_UDS": daemon_socket_path,
        "BASECAMP_RUN_ID": run_id,
        "BASECAMP_REPORT_TOKEN": report_token,
        "BASECAMP_AGENT_ID": agent_id,
        "BASECAMP_PARENT_SESSION": dispatcher_node_id,
        "BASECAMP_AGENT_DEPTH": str(child_depth),
        # Daemon-spawned children are backgrounded workers, never user-facing.
        "BASECAMP_USER_FACING": "0",
    }
    # The public handle is daemon-owned: never let a requester-supplied spec.env
    # value survive as the child's identity.
    child_env.pop("BASECAMP_AGENT_HANDLE", None)
    if agent_handle is not None:
        child_env["BASECAMP_AGENT_HANDLE"] = agent_handle
    return child_env


async def spawn_agent_process(
    *,
    run_id: str,
    spec: DispatchSpec,
    agent_id: str,
    report_token: str,
    daemon_socket_path: str,
    dispatcher_node_id: str,
    child_depth: int,
    result_path: str | Path,
    agent_handle: str | None = None,
    fork_source_path: str | None = None,
) -> asyncio.subprocess.Process:
    argv = build_runner_argv(
        result_path=result_path,
        spec=spec,
        fork_source_path=fork_source_path,
    )
    child_env = build_child_env(
        spec_env=spec.env,
        daemon_socket_path=daemon_socket_path,
        run_id=run_id,
        report_token=report_token,
        agent_id=agent_id,
        dispatcher_node_id=dispatcher_node_id,
        child_depth=child_depth,
        agent_handle=agent_handle,
    )

    return await asyncio.create_subprocess_exec(
        *argv,
        cwd=spec.cwd,
        env=child_env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )


def _process_group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_process_group(
    pgid: int | None,
    *,
    escalation_s: float = 5.0,
    poll_s: float = 0.1,
) -> None:
    # Never signal pgid 0 or 1: they may target the caller or system processes.
    if pgid is None or pgid <= 1:
        return

    try:
        os.killpg(pgid, signal.SIGTERM)
    except OSError:
        return

    deadline = time.monotonic() + escalation_s
    while time.monotonic() < deadline:
        if not _process_group_alive(pgid):
            return
        time.sleep(poll_s)

    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        return


def _process_group_is_runner(pgid: int) -> bool:
    if pgid <= 1:
        return False

    try:
        result = subprocess.run(
            ["ps", "-p", str(pgid), "-o", "args="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False

    return any(f"-m {module}" in result.stdout for module in _RUNNER_MODULE_MATCHES)


def terminate_process_group_if_runner(
    pgid: int | None,
    *,
    escalation_s: float = 5.0,
    poll_s: float = 0.1,
) -> None:
    # Guard against PID/PGID reuse before signalling.
    if pgid is None or not _process_group_is_runner(pgid):
        return

    terminate_process_group(pgid, escalation_s=escalation_s, poll_s=poll_s)


def _sidecar_final_outcome(result_path: str | Path) -> tuple[str, str | None, str | None] | None:
    """Map a runner's recorded sidecar ``final`` to a terminal outcome, or None.

    Uses the same ok->completed / else->failed mapping as ``handle_result_report``
    so every finalizer agrees on the terminal state a reported run would reach.
    Returns None when no ``final`` is recorded.
    """
    sidecar = load_run_result(result_path)
    final = sidecar.final if sidecar else None
    if final is None:
        return None
    status = "completed" if final.status == "ok" else "failed"
    return status, final.result, final.error


def _restart_reconcile_outcome(row: dict[str, object]) -> tuple[str, str | None, str | None]:
    """Honor a runner's recorded sidecar ``final`` when reconciling at restart.

    A runner writes its final result before it exits, so a run left nonterminal
    by a daemon crash can already have a completed result on disk that neither
    the (dead) reaper nor the unprocessed ``result_report`` ever recorded. As the
    only finalizer left for that run, reconciliation must prefer it — otherwise it
    reintroduces, via the restart path, the very clobbering the reaper now avoids.
    Fall back to the generic restart failure only when no ``final`` exists. The
    original spawn ``HOME`` is not recoverable here (the stored spec env is
    redacted), so the sidecar is resolved under the daemon's own home: correct
    when the daemon and dispatcher share a user, and otherwise a safe miss that
    falls through to the failure below.
    """
    agent_id = row.get("agent_id")
    run_id = row.get("id")
    if isinstance(agent_id, str) and isinstance(run_id, str):
        outcome = _sidecar_final_outcome(run_result_path(agent_id, run_id))
        if outcome is not None:
            return outcome
    return "failed", None, "daemon_restart_reconciled"


def reconcile_orphaned_runs(store: Store) -> None:
    for row in store.get_nonterminal_runs():
        pgid = row.get("pgid")
        if isinstance(pgid, int):
            try:
                terminate_process_group_if_runner(pgid, escalation_s=2.0)
            except OSError:
                pass

        status, result, error = _restart_reconcile_outcome(row)
        store.set_run_result_if_unset(
            run_id=row["id"],
            status=status,
            result=result,
            error=error,
        )


def _reap_outcome(exit_code: int, result_path: str | Path) -> tuple[str, str | None, str | None]:
    """Finalization for a reaped runner, preferring its recorded final result.

    The runner writes its final result to the sidecar *before* the process
    exits, so once we have observed the exit that record is a reliable
    happens-before signal. Deriving the run outcome from it — with the same
    ok->completed / else->failed mapping as ``handle_result_report`` — instead
    of always marking ``failed`` means the exit-code path and the async
    ``result_report`` frame agree on the terminal state. Whichever finalizes
    first, the run lands in the right status, closing the race that let a
    completed run be recorded as failed. The ``failed`` fallback stays for a
    runner that died before recording any final result.
    """
    outcome = _sidecar_final_outcome(result_path)
    if outcome is not None:
        return outcome
    return (
        "failed",
        None,
        f"agent process exited (code {exit_code}) without reporting a result",
    )


async def reap_agent_process(
    *,
    run_id: str,
    process: asyncio.subprocess.Process,
    registry: Registry,
    store: Store,
    on_finalize: ProcessExitHook,
    result_path: str | Path,
) -> None:
    exit_code = await process.wait()
    try:
        await asyncio.to_thread(store.set_run_exit_code, run_id=run_id, exit_code=exit_code)

        status, result, error = await asyncio.to_thread(_reap_outcome, exit_code, result_path)
        finalized = await asyncio.to_thread(
            store.set_run_result_if_unset,
            run_id=run_id,
            status=status,
            result=result,
            error=error,
        )
        if finalized:
            await on_finalize(run_id)
    finally:
        registry.pop_process(run_id)
