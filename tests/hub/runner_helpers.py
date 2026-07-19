"""Shared runner test helpers: context factory and sidecar attempt writer."""

from __future__ import annotations

from pathlib import Path

from basecamp.hub.swarm.run_result import (
    RunResultAttempt,
    RunResultSidecar,
    RunResultStatus,
    load_run_result,
    write_run_result,
)
from basecamp.hub.swarm.runner import RunnerContext


def _context(tmp_path: Path) -> RunnerContext:
    return RunnerContext(
        daemon_uds=str(tmp_path / "daemon.sock"),
        run_id="run-1",
        report_token="token-1",
        agent_id="agent-1",
        agent_handle="amber-fox-a1b2c3",
        parent_session="session-1",
        agent_depth=1,
        result_path=tmp_path / "result.json",
    )


def _append_attempt(
    path: Path,
    *,
    attempt: int,
    status: RunResultStatus = "ok",
    result: str | None,
    error: str | None = None,
) -> None:
    sidecar = load_run_result(path) or RunResultSidecar(
        run_id="run-1",
        agent_id="agent-1",
        attempts=[],
        final=None,
    )
    sidecar.attempts.append(
        RunResultAttempt(
            attempt=attempt,
            status=status,
            result=result,
            error=error,
        )
    )
    write_run_result(path, sidecar)
