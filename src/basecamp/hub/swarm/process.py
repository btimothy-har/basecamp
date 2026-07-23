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


def _process_group_verified_dead(pgid: int | None) -> bool:
    """True only when the ps probe ran and found no live process in the group.

    Returns False when pgid is None, the probe raised OSError, or a live process
    was found — callers must defer teardown in all those cases rather than risk
    force-removing a possibly-live runner's workspace.
    """
    if pgid is None or pgid <= 1:
        return False
    try:
        result = subprocess.run(
            ["ps", "-p", str(pgid), "-o", "pid="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return not result.stdout.strip()


def terminate_process_group_if_runner(
    pgid: int | None,
    *,
    escalation_s: float = 5.0,
    poll_s: float = 0.1,
) -> bool:
    # Guard against PID/PGID reuse before signalling. Returns True when the group
    # was verified as a runner and signalled; False when liveness was unverified
    # (pgid missing or the ps probe failed) so callers can defer workspace teardown.
    if pgid is None or not _process_group_is_runner(pgid):
        return False

    terminate_process_group(pgid, escalation_s=escalation_s, poll_s=poll_s)
    return True


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


def _spec_owned_worktree(spec: object) -> str | None:
    return spec.get("owned_worktree") if isinstance(spec, dict) else None


def _teardown_from_spec(worktree: str, spec: object) -> None:
    """Tear down a workspace using branch fields from a parsed spec dict.

    The v27 marker is the ``branch_created`` key itself: its presence means the row
    was dispatched with v27 fields (owned_branch may legitimately be null for
    report/ask runs) and gets unconditional --force. Its absence means a pre-upgrade
    row, which gets non-force removal to preserve dirty residuals during the
    one-time upgrade window.
    """
    if not isinstance(spec, dict):
        teardown_agent_workspace(worktree)
        return
    teardown_agent_workspace(
        worktree,
        branch=spec.get("owned_branch"),
        branch_base=spec.get("branch_base"),
        branch_created=spec.get("branch_created", False),
        force="branch_created" in spec,
    )


def reconcile_orphaned_runs(store: Store) -> None:
    for row in store.get_nonterminal_runs():
        try:
            _reconcile_nonterminal_row(store, row)
        except Exception:
            continue

    _reconcile_terminal_worktrees(store)


def _reconcile_nonterminal_row(store: Store, row: dict[str, object]) -> None:
    pgid = row.get("pgid")
    pgid_int = pgid if isinstance(pgid, int) else None
    if pgid_int is not None:
        try:
            terminate_process_group_if_runner(pgid_int, escalation_s=2.0)
        except OSError:
            pass

    status, result, error = _restart_reconcile_outcome(row)
    store.set_run_result_if_unset(
        run_id=row["id"],
        status=status,
        result=result,
        error=error,
    )

    # A run orphaned by a daemon crash never had its reaper fire, so tear down its workspace
    # here — the reaper's counterpart. The merged-worktree sweep can't cover this case: a
    # crash-interrupted run's branch has not been merged yet. Tear down only when the group is
    # PROVABLY dead (ps ran, no live process): terminate_process_group issues SIGKILL without
    # confirming it landed, so a runner wedged in uninterruptible I/O could still be touching
    # its tree. A just-terminated-but-not-yet-reaped group, a missing pgid, or a failed ps probe
    # all defer to the next reconcile / session sweep rather than force-removing a live tree.
    if not _process_group_verified_dead(pgid_int):
        return
    spec = row.get("spec_json")
    owned_worktree = _spec_owned_worktree(spec)
    if owned_worktree:
        _teardown_from_spec(owned_worktree, spec)


def _reconcile_terminal_worktrees(store: Store) -> None:
    # A run finalized via result_report whose daemon died before the reaper's teardown fired
    # leaks its workspace forever — the nonterminal pass above never sees it. Sweep recently
    # terminal rows and tear down any whose worktree path still exists on disk and whose pgid
    # is provably dead. Do not re-finalize their status.
    for row in store.get_recent_runs_with_owned_worktree():
        try:
            worktree = row["spec_json"].get("owned_worktree")
            if not (isinstance(worktree, str) and os.path.exists(worktree)):
                continue
            # Tear down only when the row's pgid is provably dead; a None or unverifiable
            # pgid means a possibly-live runner still owns the tree. Deferred/unverifiable
            # residue falls to the session-start sweep (the documented last resort; a
            # zero-commit agent branch at its base reads as integrated there, so it self-heals).
            if not _process_group_verified_dead(row.get("pgid")):
                continue
            _teardown_from_spec(worktree, row["spec_json"])
        except Exception:
            continue


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


def teardown_agent_workspace(
    worktree: str,
    *,
    branch: str | None = None,
    branch_base: str | None = None,
    branch_created: bool = False,
    force: bool = True,
) -> None:
    """Remove a dispatched agent's worktree at run end.

    A worktree is transient: dirty state is discarded by design — commits are the only
    durable output of a run. The branch is deleted only when this run minted it
    (branch_created) and it has zero commits ahead of branch_base (nothing happened);
    otherwise the branch is durable. Ask/report runs pass branch=None, so only the
    worktree is removed.

    ``force`` controls ``--force`` on ``git worktree remove``. v27-dispatched runs
    always pass ``True`` (unconditional discard). Pre-upgrade rows — whose spec_json
    predates the v27 branch keys — pass ``False`` to preserve the old contract's
    dirty-residual behavior during the one-time upgrade window.

    If common-dir resolution fails the worktree is already gone; return without touching the
    branch — the session-start sweep is the backstop for orphan branches. Best-effort:
    subprocess timeouts (15s/30s), OSError and SubprocessError suppressed, no raised
    exceptions. Run from the main checkout (resolved via the common git dir) since a
    worktree cannot remove itself. Branch deletion happens after worktree removal because
    git refuses to delete a checked-out branch.
    """
    try:
        common = subprocess.run(
            ["git", "-C", worktree, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if common.returncode != 0 or not common.stdout.strip():
            return
        main_root = os.path.dirname(common.stdout.strip())
        subprocess.run(
            ["git", "-C", main_root, "worktree", "unlock", worktree],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        remove_argv = ["git", "-C", main_root, "worktree", "remove"]
        if force:
            remove_argv.append("--force")
        remove_argv.append(worktree)
        subprocess.run(
            remove_argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if branch and branch_created and branch_base:
            rev_list = subprocess.run(
                ["git", "-C", main_root, "rev-list", "--count", f"{branch_base}..{branch}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            if rev_list.returncode == 0 and rev_list.stdout.strip() == "0":
                subprocess.run(
                    ["git", "-C", main_root, "branch", "-D", branch],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=15,
                )
    except (OSError, subprocess.SubprocessError):
        return


async def reap_agent_process(
    *,
    run_id: str,
    process: asyncio.subprocess.Process,
    registry: Registry,
    store: Store,
    on_finalize: ProcessExitHook,
    result_path: str | Path,
    owned_worktree: str | None = None,
    owned_branch: str | None = None,
    branch_base: str | None = None,
    branch_created: bool = False,
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
        if owned_worktree:
            await asyncio.to_thread(
                teardown_agent_workspace,
                owned_worktree,
                branch=owned_branch,
                branch_base=branch_base,
                branch_created=branch_created,
            )
