"""Companion snapshot models, loader, and state panel rendering."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel


class CompanionBaseModel(BaseModel):
    """Base model for companion snapshot payloads."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class CompanionTask(CompanionBaseModel):
    """Task entry in a companion snapshot."""

    label: str
    status: str
    notes: str | None = None


class CompanionWorktree(CompanionBaseModel):
    """Worktree metadata in a companion snapshot."""

    label: str
    branch: str | None = None
    path: str


class CompanionProgress(CompanionBaseModel):
    """Progress section in a companion snapshot."""

    completed: int = 0
    total: int = 0


class CompanionSnapshot(CompanionBaseModel):
    """Top-level companion snapshot payload."""

    version: int
    session_id: str
    updated_at: str
    goal: str | None = None
    tasks: list[CompanionTask] = Field(default_factory=list)
    progress: CompanionProgress = Field(default_factory=CompanionProgress)
    agent_mode: str | None = None
    worktree: CompanionWorktree | None = None
    repo_name: str | None = None
    model: str | None = None
    skills_used: list[str] = Field(default_factory=list)
    effective_cwd: str = ""


def companion_snapshot_path(session_id: str, base_dir: Path | None = None) -> Path:
    """Return a snapshot path for a session id."""

    resolved_base_dir = base_dir or (Path.home() / ".pi" / "companion")
    sanitized_session_id = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)
    return resolved_base_dir / f"{sanitized_session_id}.json"


def load_snapshot(path: Path) -> CompanionSnapshot | None:
    """Load a snapshot file into a model, returning None on any failure."""

    try:
        raw_payload = path.read_text(encoding="utf-8")
        parsed_payload = json.loads(raw_payload)
        return CompanionSnapshot.model_validate(parsed_payload)
    except (OSError, json.JSONDecodeError, ValidationError):
        return None


def render_state_lines(snapshot: CompanionSnapshot | None) -> list[str]:
    """Render the state panel as plain display lines."""

    if snapshot is None:
        return ["Waiting for session…"]

    goal = snapshot.goal or "No goal set"
    mode = snapshot.agent_mode or "unknown"

    if snapshot.worktree is None:
        worktree_text = "none"
    elif snapshot.worktree.branch:
        worktree_text = f"{snapshot.worktree.label} ({snapshot.worktree.branch})"
    else:
        worktree_text = snapshot.worktree.label

    progress_text = f"{snapshot.progress.completed}/{snapshot.progress.total}"
    short_session_id = snapshot.session_id.replace("-", "")[-6:]

    lines = [
        f"🎯 {goal}",
        f"Mode: {mode} | Worktree: {worktree_text} | Progress: {progress_text} | Session: {short_session_id}",
        "Tasks:",
    ]

    marker_by_status = {
        "completed": "✓",
        "active": "→",
        "pending": "☐",
    }

    visible_task_count = 0
    for task in snapshot.tasks:
        if task.status == "deleted":
            continue

        visible_task_count += 1
        marker = marker_by_status.get(task.status, "•")
        lines.append(f"{marker} {task.label}")

    if visible_task_count == 0:
        lines.append("(no tasks)")

    if snapshot.skills_used:
        lines.append(f"📖 {', '.join(snapshot.skills_used)}")

    return lines
