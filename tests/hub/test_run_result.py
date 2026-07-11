from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from basecamp.hub.swarm.run_result import (
    FinalRunResult,
    RunResultAttempt,
    RunResultSidecar,
    agent_session_file,
    load_run_result,
    run_result_path,
    write_run_result,
)


def test_run_result_path_uses_run_owned_agent_directory() -> None:
    fake_home = Path("/tmp/fake-home")

    assert run_result_path("agent-1", "run-1", fake_home) == (
        fake_home / ".pi" / "basecamp" / "swarm" / "agents" / "agent-1" / "runs" / "run-1" / "result.json"
    )


def test_run_result_path_is_unique_per_run_id() -> None:
    fake_home = Path("/tmp/fake-home")

    first = run_result_path("agent-1", "run-1", fake_home)
    second = run_result_path("agent-1", "run-2", fake_home)

    assert first != second
    assert first.parent == fake_home / ".pi" / "basecamp" / "swarm" / "agents" / "agent-1" / "runs" / "run-1"
    assert second.parent == fake_home / ".pi" / "basecamp" / "swarm" / "agents" / "agent-1" / "runs" / "run-2"


def test_agent_session_file_returns_newest_absolute_session_file(tmp_path: Path) -> None:
    agent_id = "agent-1"
    session_dir = tmp_path / ".pi" / "basecamp" / "swarm" / "agents" / agent_id / "session"
    session_dir.mkdir(parents=True)
    older = session_dir / f"2026-01-01T00-00-00_{agent_id}.jsonl"
    newer = session_dir / f"2026-01-01T00-00-01_{agent_id}.jsonl"
    older.write_text("{}\n", encoding="utf-8")
    newer.write_text("{}\n", encoding="utf-8")

    assert agent_session_file(agent_id, tmp_path) == newer.resolve()
    assert agent_session_file("missing-agent", tmp_path) is None


def test_agent_session_file_ignores_symlinks(tmp_path: Path) -> None:
    agent_id = "agent-1"
    session_dir = tmp_path / ".pi" / "basecamp" / "swarm" / "agents" / agent_id / "session"
    session_dir.mkdir(parents=True)
    real = session_dir / f"2026-01-01T00-00-00_{agent_id}.jsonl"
    real.write_text("{}\n", encoding="utf-8")

    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}\n", encoding="utf-8")
    # A symlink whose name sorts AFTER the real file must still be ignored.
    link = session_dir / f"9999-99-99T00-00-00_{agent_id}.jsonl"
    link.symlink_to(outside)

    assert agent_session_file(agent_id, tmp_path) == real.resolve()


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


def test_load_run_result_returns_none_for_malformed_json(tmp_path: Path) -> None:
    file_path = tmp_path / "result.json"
    file_path.write_text("{", encoding="utf-8")

    assert load_run_result(file_path) is None


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
