"""Data models for dispatch tasks."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    STAGED = "staged"
    DISPATCHED = "dispatched"
    CLOSED = "closed"


class TaskEntry(BaseModel):
    """Metadata for a dispatch task.

    Stored in the per-project index at ~/.basecamp/tasks/{project}.json.
    """

    name: str
    project: str
    task_dir: str
    session_id: str
    parent_session_id: str
    status: TaskStatus = TaskStatus.STAGED
    model: str = "sonnet"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime | None = None
