"""Queue input contract for transcript processing jobs."""

from __future__ import annotations

from pi_memory.constants import JOB_KIND_PROCESS_TRANSCRIPT
from pi_memory.db.models import Job
from pi_memory.infra.job_queue.store import JobStore
from pi_memory.ingest import IngestResult
from pi_memory.pipeline.reconciliation import EnqueueSpec


def process_transcript_job_spec(result: IngestResult) -> EnqueueSpec | None:
    """Build the enqueue spec for transcript processing."""
    if result.entries_ingested == 0:
        return None

    return EnqueueSpec(
        kind=JOB_KIND_PROCESS_TRANSCRIPT,
        payload_json={
            "transcript_id": result.transcript_id,
            # Remaining fields are audit/debug context for inspecting queued work.
            # The runner uses SQLite as truth and only requires transcript_id.
            "session_id": result.session_id,
            "observation_id": result.observation_id,
            "entries_ingested": result.entries_ingested,
            "cursor_offset": result.cursor_offset,
            "file_size": result.file_size,
            "observed_at": result.observed_at.isoformat(),
            "malformed_lines": result.malformed_lines,
            "unsupported_lines": result.unsupported_lines,
        },
    )


def enqueue_process_transcript_job(store: JobStore, result: IngestResult) -> Job | None:
    """Enqueue transcript processing for an ingest result with new entries."""
    spec = process_transcript_job_spec(result)
    if spec is None:
        return None
    return store.enqueue(**spec.model_dump())
