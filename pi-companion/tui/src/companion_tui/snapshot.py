"""Companion snapshot models, loader, and state panel rendering."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

from companion_tui.diff import WorkspaceStatus


class CompanionBaseModel(BaseModel):
    """Base model for companion snapshot payloads."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class CompanionTask(CompanionBaseModel):
    """Task entry in a companion snapshot."""

    label: str
    status: str
    notes: str | None = None
    description: str = ""
    criteria: str = ""


class CompanionWorktree(CompanionBaseModel):
    """Worktree metadata in a companion snapshot."""

    label: str
    branch: str | None = None
    path: str


class CompanionProgress(CompanionBaseModel):
    """Progress section in a companion snapshot."""

    completed: int = 0
    total: int = 0


class CompanionGoal(CompanionBaseModel):
    """A goal cycle (current or archived) in a companion snapshot."""

    goal: str
    tasks: list[CompanionTask] = Field(default_factory=list)
    agent_mode: str | None = None
    active: bool = False
    archived_at: str | None = None
    progress: CompanionProgress = Field(default_factory=CompanionProgress)


class CompanionSnapshot(CompanionBaseModel):
    """Top-level companion snapshot payload."""

    version: int
    session_id: str
    title: str | None = None
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


def default_companion_snapshot_dir() -> Path:
    """Return the default Basecamp companion snapshot directory."""

    return Path.home() / ".pi" / "basecamp" / "companion" / "snapshots"


def companion_snapshot_path(session_id: str, base_dir: Path | None = None) -> Path:
    """Return a snapshot path for a session id."""

    resolved_base_dir = base_dir or default_companion_snapshot_dir()
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


def collapse_home(path: str) -> str:
    """Collapse absolute home paths to `~` form for compact display."""

    home = str(Path.home())
    if path == home or path.startswith(f"{home}/"):
        return f"~{path[len(home) :]}"
    return path


def render_workspace_lines(snapshot: CompanionSnapshot | None, status: WorkspaceStatus | None) -> list[str]:
    """Render the workspace/git panel as plain display lines."""

    if snapshot is None and status is None:
        return ["Waiting for session…"]

    repo = (snapshot.repo_name if snapshot else None) or "—"
    worktree_label = snapshot.worktree.label if snapshot and snapshot.worktree else None
    worktree_branch = snapshot.worktree.branch if snapshot and snapshot.worktree else None
    branch = status.branch if status else worktree_branch
    head = worktree_label or branch or "detached"

    lines = [f"📁 {repo} · {head}"]

    if status is not None:
        base = status.base_branch or "?"
        lines.append(f"⌥ {branch or '?'} → {base} (+{status.ahead})")
        lines.append(
            f"± {status.changed_files} changed · {status.staged} staged · "
            f"{status.modified} modified · {status.untracked} new"
        )

    if snapshot is not None and snapshot.effective_cwd:
        lines.append(f"📂 {collapse_home(snapshot.effective_cwd)}")

    return lines
