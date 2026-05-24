"""Queue input contract for interpretation quality assessment jobs."""

from __future__ import annotations

from pi_memory.constants import (
    JOB_KIND_ASSESS_INTERPRETATION_QUALITY,
    JOB_KIND_INTERPRET_SESSION,
)
from pi_memory.db.models import Job
from pi_memory.infra.job_queue.store import JobStore
from pi_memory.pipeline.reconciliation import EnqueueSpec


def assess_interpretation_quality_idempotency_key(snapshot_id: int) -> str:
    return f"{JOB_KIND_ASSESS_INTERPRETATION_QUALITY}:{JOB_KIND_INTERPRET_SESSION}:{snapshot_id}"


def assess_interpretation_quality_job_spec(
    *,
    snapshot_id: int,
    session_id: str,
    interpretation_job_id: int | None = None,
    idempotency_key: str | None = None,
) -> EnqueueSpec:
    """Build the enqueue spec for interpretation quality assessment."""
    return EnqueueSpec(
        kind=JOB_KIND_ASSESS_INTERPRETATION_QUALITY,
        payload_json={
            "snapshot_id": snapshot_id,
            "session_id": session_id,
            "interpretation_job_id": interpretation_job_id,
        },
        idempotency_key=idempotency_key,
    )


def enqueue_assess_interpretation_quality_job(
    store: JobStore,
    *,
    snapshot_id: int,
    session_id: str,
    interpretation_job_id: int | None = None,
    idempotency_key: str | None = None,
) -> Job:
    """Enqueue quality assessment after an interpretation snapshot is written."""
    return store.enqueue(
        **assess_interpretation_quality_job_spec(
            snapshot_id=snapshot_id,
            session_id=session_id,
            interpretation_job_id=interpretation_job_id,
            idempotency_key=idempotency_key,
        ).model_dump(),
    )
