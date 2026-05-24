"""Queue input contract for memory projection jobs."""

from __future__ import annotations

from pi_memory.constants import (
    JOB_KIND_ASSESS_INTERPRETATION_QUALITY,
    JOB_KIND_PROJECT_MEMORY_RECORDS,
)
from pi_memory.db.models import Job
from pi_memory.infra.job_queue.store import JobStore
from pi_memory.pipeline.reconciliation.contracts import EnqueueSpec


def project_memory_records_idempotency_key(quality_report_id: int) -> str:
    return f"{JOB_KIND_PROJECT_MEMORY_RECORDS}:{JOB_KIND_ASSESS_INTERPRETATION_QUALITY}:{quality_report_id}"


def project_memory_records_job_spec(
    *,
    quality_report_id: int,
    session_id: str,
    quality_job_id: int | None = None,
    idempotency_key: str | None = None,
) -> EnqueueSpec:
    """Build the enqueue spec for projecting one quality report."""
    return EnqueueSpec(
        kind=JOB_KIND_PROJECT_MEMORY_RECORDS,
        payload_json={
            "scope": "quality_report",
            "quality_report_id": quality_report_id,
            "session_id": session_id,
            "quality_job_id": quality_job_id,
        },
        max_attempts=3,
        idempotency_key=idempotency_key,
    )


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
        **project_memory_records_job_spec(
            quality_report_id=quality_report_id,
            session_id=session_id,
            quality_job_id=quality_job_id,
            idempotency_key=idempotency_key,
        ).model_dump(),
    )


def enqueue_rebuild_memory_projection_job(store: JobStore) -> Job:
    """Enqueue an upsert rebuild pass for all canonical memory projections."""
    return store.enqueue(
        JOB_KIND_PROJECT_MEMORY_RECORDS,
        payload_json={"scope": "all"},
        max_attempts=3,
    )
