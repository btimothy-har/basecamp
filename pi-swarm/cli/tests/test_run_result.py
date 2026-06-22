from __future__ import annotations

from pathlib import Path

import pytest
from pi_swarm.run_result import (
    FinalRunResult,
    RunResultAttempt,
    RunResultSidecar,
    load_run_result,
    run_result_path,
    write_run_result,
)
from pydantic import ValidationError


def test_run_result_path_uses_run_owned_agent_directory() -> None:
    fake_home = Path("/tmp/fake-home")

    assert run_result_path("agent-1", "run-1", fake_home) == (
        fake_home
        / ".pi"
        / "basecamp"
        / "swarm"
        / "agents"
        / "agent-1"
        / "runs"
        / "run-1"
        / "result.json"
    )


def test_run_result_path_is_unique_per_run_id() -> None:
    fake_home = Path("/tmp/fake-home")

    first = run_result_path("agent-1", "run-1", fake_home)
    second = run_result_path("agent-1", "run-2", fake_home)

    assert first != second
    assert first.parent == fake_home / ".pi" / "basecamp" / "swarm" / "agents" / "agent-1" / "runs" / "run-1"
    assert second.parent == fake_home / ".pi" / "basecamp" / "swarm" / "agents" / "agent-1" / "runs" / "run-2"


def test_run_result_models_validate_and_round_trip() -> None:
    sidecar = RunResultSidecar(
        run_id="run-1",
        agent_id="agent-1",
        attempts=[
            RunResultAttempt(attempt=1, status="error", result=None, error="empty"),
            RunResultAttempt(attempt=2, status="ok", result="done", error=None),
        ],
        final=FinalRunResult(status="ok", result="done", error=None, retry_count=1),
    )

    assert RunResultSidecar.model_validate(sidecar.model_dump()) == sidecar

    with pytest.raises(ValidationError):
        RunResultAttempt.model_validate({"attempt": 1, "status": "failed", "result": None, "error": "bad"})


def test_write_and_load_run_result_are_atomic_round_trip(tmp_path: Path) -> None:
    file_path = run_result_path("agent-1", "run-1", tmp_path)
    sidecar = RunResultSidecar(
        run_id="run-1",
        agent_id="agent-1",
        attempts=[RunResultAttempt(attempt=1, status="ok", result="done", error=None)],
        final=None,
    )

    assert load_run_result(file_path) is None

    write_run_result(file_path, sidecar)

    assert load_run_result(file_path) == sidecar
    assert not list(file_path.parent.glob("*.tmp"))
