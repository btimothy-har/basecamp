"""Job enqueue helpers for session interpretation."""

from __future__ import annotations

from pi_memory.analysis import TranscriptAnalysisResult
from pi_memory.db import JOB_KIND_INTERPRET_SESSION, Job
from pi_memory.jobs.store import JobStore


def enqueue_interpret_session_job(
    store: JobStore,
    *,
    transcript_id: int,
    session_id: str,
    analysis_result: TranscriptAnalysisResult,
    process_job_id: int | None = None,
) -> Job:
    """Enqueue session interpretation after a successful Phase 5A analysis."""
    return store.enqueue(
        JOB_KIND_INTERPRET_SESSION,
        payload_json={
            "transcript_id": transcript_id,
            "analysis_run_id": analysis_result.analysis_run_id,
            # Remaining fields are audit/debug context for inspecting queued work.
            # The runner uses SQLite as truth and only requires transcript_id and analysis_run_id.
            "session_id": session_id,
            "process_job_id": process_job_id,
            "analyzed_through_entry_id": analysis_result.analyzed_through_entry_id,
            "analyzed_through_byte_offset": analysis_result.analyzed_through_byte_offset,
            "activity_count": analysis_result.activity_count,
            "episode_count": analysis_result.episode_count,
            "manifest_count": analysis_result.manifest_count,
        },
    )
