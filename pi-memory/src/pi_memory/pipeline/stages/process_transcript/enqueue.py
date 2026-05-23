"""Queue input contract for transcript processing jobs."""

from __future__ import annotations

from pi_memory.db.constants import JOB_KIND_PROCESS_TRANSCRIPT
from pi_memory.db.models import Job
from pi_memory.infra.job_queue.store import JobStore
from pi_memory.ingest import IngestResult


def enqueue_process_transcript_job(store: JobStore, result: IngestResult) -> Job | None:
    """Enqueue transcript processing for an ingest result with new entries."""
    if result.entries_ingested == 0:
        return None

    return store.enqueue(
        JOB_KIND_PROCESS_TRANSCRIPT,
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
