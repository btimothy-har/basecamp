"""Subprocess lifecycle helpers for daemon-dispatched agents."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from .frames import DispatchSpec
from .registry import Registry
from .run_result import run_result_path
from .store import Store

ProcessExitHook = Callable[[str], Awaitable[None]]


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
        "pi_swarm.runner",
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
    agent_handle: str | None = None,
    fork_source_path: str | None = None,
) -> asyncio.subprocess.Process:
    result_path = run_result_path(agent_id, run_id, home_dir=spec.env.get("HOME"))
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
    )


async def reap_agent_process(
    *,
    run_id: str,
    process: asyncio.subprocess.Process,
    registry: Registry,
    store: Store,
    on_finalize: ProcessExitHook,
) -> None:
    exit_code = await process.wait()
    try:
        await asyncio.to_thread(store.set_run_exit_code, run_id=run_id, exit_code=exit_code)

        finalized = await asyncio.to_thread(
            store.set_run_result_if_unset,
            run_id=run_id,
            status="failed",
            result=None,
            error=f"agent process exited (code {exit_code}) without reporting a result",
        )
        if finalized:
            await on_finalize(run_id)
    finally:
        registry.pop_process(run_id)
