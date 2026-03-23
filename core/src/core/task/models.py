"""Data models for dispatch tasks."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class TaskEntry(BaseModel):
    """Metadata for a dispatch task.

    Stored in the per-project index at ~/.basecamp/tasks/{project}.json.
    A task is considered dispatched when worker_session_id is set.
    """

    name: str
    project: str
    task_dir: str
    parent_session_id: str
    worker_session_id: str | None = None
    model: str = "sonnet"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
