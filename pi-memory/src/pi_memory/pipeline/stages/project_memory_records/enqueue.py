"""Queue input contract for memory projection jobs."""

from __future__ import annotations

from pi_memory.constants import JOB_KIND_PROJECT_MEMORY_RECORDS
from pi_memory.db.models import Job
from pi_memory.infra.job_queue.store import JobStore


def enqueue_project_memory_records_job(
    store: JobStore,
    *,
    quality_report_id: int,
    session_id: str,
    quality_job_id: int | None = None,
    idempotency_key: str | None = None,
) -> Job:
    """Enqueue short-term memory projection for one quality report."""
    return store.enqueue(
        JOB_KIND_PROJECT_MEMORY_RECORDS,
        payload_json={
            "scope": "quality_report",
            "quality_report_id": quality_report_id,
            "session_id": session_id,
            "quality_job_id": quality_job_id,
        },
        max_attempts=3,
        idempotency_key=idempotency_key,
    )


def enqueue_rebuild_memory_projection_job(store: JobStore) -> Job:
    """Enqueue an upsert rebuild pass for all canonical memory projections."""
    return store.enqueue(
        JOB_KIND_PROJECT_MEMORY_RECORDS,
        payload_json={"scope": "all"},
        max_attempts=3,
    )
