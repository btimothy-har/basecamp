"""Read-only job inspection serialization helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pi_memory.db import Job

JOB_INSPECTION_FIELDS = (
    "id",
    "kind",
    "status",
    "payload_json",
    "result_json",
    "priority",
    "due_at",
    "attempts",
    "max_attempts",
    "run_id",
    "claimed_at",
    "claimed_by",
    "started_at",
    "heartbeat_at",
    "lease_expires_at",
    "running_pid",
    "finished_at",
    "exit_code",
    "last_error",
    "created_at",
    "updated_at",
)

DATETIME_JOB_INSPECTION_FIELDS = {
    "due_at",
    "claimed_at",
    "started_at",
    "heartbeat_at",
    "lease_expires_at",
    "finished_at",
    "created_at",
    "updated_at",
}


def serialize_job(job: Job) -> dict[str, Any]:
    """Return a JSON-safe read-only inspection payload for a job row."""
    payload: dict[str, Any] = {}
    for field in JOB_INSPECTION_FIELDS:
        value = getattr(job, field)
        if field in DATETIME_JOB_INSPECTION_FIELDS:
            payload[field] = _serialize_datetime(value)
        else:
            payload[field] = value
    return payload


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
