"""Queue input contract for interpretation quality assessment jobs."""

from __future__ import annotations

from pi_memory.db.constants import JOB_KIND_ASSESS_INTERPRETATION_QUALITY
from pi_memory.db.models import Job
from pi_memory.infra.job_queue.store import JobStore


def enqueue_assess_interpretation_quality_job(
    store: JobStore,
    *,
    snapshot_id: int,
    session_id: str,
    interpretation_job_id: int | None = None,
) -> Job:
    """Enqueue quality assessment after an interpretation snapshot is written."""
    return store.enqueue(
        JOB_KIND_ASSESS_INTERPRETATION_QUALITY,
        payload_json={
            "snapshot_id": snapshot_id,
            "session_id": session_id,
            "interpretation_job_id": interpretation_job_id,
        },
    )
