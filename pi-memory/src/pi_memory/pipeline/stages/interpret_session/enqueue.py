"""Queue input contract for session interpretation jobs."""

from __future__ import annotations

from pi_memory.analysis import TranscriptAnalysisResult
from pi_memory.db import JOB_KIND_INTERPRET_SESSION, Job
from pi_memory.infra.job_queue.store import JobStore
from pi_memory.pipeline.utils import payloads


def enqueue_interpret_session_job(
    store: JobStore,
    *,
    transcript_id: int,
    session_id: str,
    analysis_result: TranscriptAnalysisResult,
    process_job_id: int | None = None,
) -> Job:
    """Enqueue session interpretation after a successful Phase 5A analysis."""
    return enqueue_interpret_session_job_for_analysis(
        store,
        transcript_id=transcript_id,
        session_id=session_id,
        analysis_run_id=analysis_result.analysis_run_id,
        process_job_id=process_job_id,
        analyzed_through_entry_id=analysis_result.analyzed_through_entry_id,
        analyzed_through_byte_offset=analysis_result.analyzed_through_byte_offset,
        activity_count=analysis_result.activity_count,
        episode_count=analysis_result.episode_count,
        manifest_count=analysis_result.manifest_count,
    )


def enqueue_interpret_session_job_for_analysis(
    store: JobStore,
    *,
    transcript_id: int,
    session_id: str,
    analysis_run_id: int,
    process_job_id: int | None,
    analyzed_through_entry_id: int | None,
    analyzed_through_byte_offset: int,
    activity_count: int,
    episode_count: int,
    manifest_count: int,
) -> Job:
    """Enqueue session interpretation for a known persisted analysis run."""
    return store.enqueue(
        JOB_KIND_INTERPRET_SESSION,
        payload_json=payloads.analysis_job_payload(
            transcript_id=transcript_id,
            session_id=session_id,
            analysis_run_id=analysis_run_id,
            process_job_id=process_job_id,
            analyzed_through_entry_id=analyzed_through_entry_id,
            analyzed_through_byte_offset=analyzed_through_byte_offset,
            activity_count=activity_count,
            episode_count=episode_count,
            manifest_count=manifest_count,
        ),
    )
