"""Queue input contract for durable memory promotion jobs."""

from __future__ import annotations

from pi_memory.constants import (
    JOB_KIND_ASSESS_INTERPRETATION_QUALITY,
    JOB_KIND_PROMOTE_DURABLE_MEMORY,
)
from pi_memory.db.models import Job
from pi_memory.infra.job_queue.store import JobStore
from pi_memory.pipeline.reconciliation.contracts import EnqueueSpec


def promote_durable_memory_idempotency_key(quality_report_id: int) -> str:
    return f"{JOB_KIND_PROMOTE_DURABLE_MEMORY}:{JOB_KIND_ASSESS_INTERPRETATION_QUALITY}:{quality_report_id}"


def promote_durable_memory_job_spec(
    *,
    quality_report_id: int,
    session_id: str,
    quality_job_id: int | None = None,
    idempotency_key: str | None = None,
) -> EnqueueSpec:
    """Build the enqueue spec for durable-memory promotion."""
    return EnqueueSpec(
        kind=JOB_KIND_PROMOTE_DURABLE_MEMORY,
        payload_json={
            "quality_report_id": quality_report_id,
            "session_id": session_id,
            "quality_job_id": quality_job_id,
        },
        max_attempts=5,
        idempotency_key=idempotency_key,
    )


def enqueue_promote_durable_memory_job(
    store: JobStore,
    *,
    quality_report_id: int,
    session_id: str,
    quality_job_id: int | None = None,
    idempotency_key: str | None = None,
) -> Job:
    """Enqueue durable-memory promotion for one quality report."""
    return store.enqueue(
        **promote_durable_memory_job_spec(
            quality_report_id=quality_report_id,
            session_id=session_id,
            quality_job_id=quality_job_id,
            idempotency_key=idempotency_key,
        ).model_dump(),
    )
