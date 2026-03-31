"""Data models for dispatch workers."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class WorkerStatus(str, Enum):
    STAGED = "staged"
    DISPATCHED = "dispatched"
    CLOSED = "closed"


class WorkerEntry(BaseModel):
    """Metadata for a dispatch worker.

    Stored in the per-project index at ~/.basecamp/workers/{project}.json.
    """

    name: str
    project: str
    worker_dir: str
    session_id: str
    parent_session_id: str
    status: WorkerStatus = WorkerStatus.STAGED
    model: str = "sonnet"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime | None = None
