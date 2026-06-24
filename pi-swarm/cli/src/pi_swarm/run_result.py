"""Runner result sidecar models and file helpers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

BASECAMP_RUNNER_MANAGED_RESULT = "BASECAMP_RUNNER_MANAGED_RESULT"
BASECAMP_RUN_RESULT_PATH = "BASECAMP_RUN_RESULT_PATH"
BASECAMP_RUN_ATTEMPT = "BASECAMP_RUN_ATTEMPT"

RunResultStatus = Literal["ok", "error"]


class RunResultAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    attempt: int
    status: RunResultStatus
    result: str | None
    error: str | None


class FinalRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: RunResultStatus
    result: str | None
    error: str | None
    retry_count: int


class RunResultSidecar(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    run_id: str
    agent_id: str
    attempts: list[RunResultAttempt]
    final: FinalRunResult | None


def _swarm_agents_dir(home_dir: str | Path | None = None) -> Path:
    home = Path(home_dir).expanduser() if home_dir is not None else Path.home()
    return home / ".pi" / "basecamp" / "swarm" / "agents"


def run_result_path(agent_id: str, run_id: str, home_dir: str | Path | None = None) -> Path:
    return _swarm_agents_dir(home_dir) / agent_id / "runs" / run_id / "result.json"


def agent_session_file(agent_id: str, home_dir: str | Path | None = None) -> Path | None:
    session_dir = _swarm_agents_dir(home_dir) / agent_id / "session"
    if not session_dir.is_dir():
        return None

    candidates = [path for path in session_dir.glob("*.jsonl") if path.is_file() and not path.is_symlink()]
    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime).resolve(strict=False)


def load_run_result(path: str | Path) -> RunResultSidecar | None:
    file_path = Path(path)
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return RunResultSidecar.model_validate(data)


def write_run_result(path: str | Path, sidecar: RunResultSidecar) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp_name = tempfile.mkstemp(prefix=".result.", suffix=".tmp", dir=file_path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(sidecar.model_dump(mode="json"), file, indent=2)
            file.write("\n")
        temp_path.replace(file_path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise


def find_run_result_attempt(sidecar: RunResultSidecar, attempt: int) -> RunResultAttempt | None:
    for item in sidecar.attempts:
        if item.attempt == attempt:
            return item
    return None


def set_final_run_result(
    path: str | Path,
    *,
    run_id: str,
    agent_id: str,
    final: FinalRunResult,
) -> RunResultSidecar:
    sidecar = load_run_result(path) or RunResultSidecar(
        run_id=run_id,
        agent_id=agent_id,
        attempts=[],
        final=None,
    )
    sidecar = sidecar.model_copy(update={"final": final})
    write_run_result(path, sidecar)
    return sidecar
