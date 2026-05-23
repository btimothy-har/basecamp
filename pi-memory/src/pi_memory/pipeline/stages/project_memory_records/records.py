"""Memory projection helpers for pipeline jobs."""

from __future__ import annotations

from sqlalchemy.orm import Session

from pi_memory.db.constants import MEMORY_PROJECTION_STATUS_DELETED
from pi_memory.db.models import (
    DurableMemoryItem,
    MemoryProjectionRecord,
)
from pi_memory.durable import DurableMemoryProjectionError, project_durable_memory_record
from pi_memory.projection.contracts import MemoryProjection


def project_durable_memory_record_outcome(
    session: Session,
    memory: DurableMemoryItem,
    projection: MemoryProjection,
) -> tuple[MemoryProjectionRecord | None, DurableMemoryProjectionError | None]:
    try:
        return project_durable_memory_record(session, memory, projection), None
    except DurableMemoryProjectionError as error:
        return None, error


def indexed_projection_record_count(records: list[MemoryProjectionRecord]) -> int:
    return sum(1 for record in records if record.status != MEMORY_PROJECTION_STATUS_DELETED)


def deleted_projection_record_count(records: list[MemoryProjectionRecord]) -> int:
    return sum(1 for record in records if record.status == MEMORY_PROJECTION_STATUS_DELETED)
