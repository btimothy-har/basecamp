"""Queue input contract for session interpretation jobs."""

from __future__ import annotations

from pi_memory.analysis import TranscriptAnalysisResult
from pi_memory.constants import (
    JOB_KIND_INTERPRET_SESSION,
    JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES,
)
from pi_memory.db.models import Job
from pi_memory.infra.job_queue.store import JobStore
from pi_memory.pipeline.reconciliation import EnqueueSpec
from pi_memory.pipeline.utils import payloads


def interpret_session_idempotency_key(summarize_job_id: int) -> str:
    return f"{JOB_KIND_INTERPRET_SESSION}:{JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES}:{summarize_job_id}"


def interpret_session_job_spec(
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
    idempotency_key: str | None = None,
) -> EnqueueSpec:
    """Build the enqueue spec for session interpretation."""
    return EnqueueSpec(
        kind=JOB_KIND_INTERPRET_SESSION,
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
        idempotency_key=idempotency_key,
    )


def enqueue_interpret_session_job(
    store: JobStore,
    *,
    transcript_id: int,
    session_id: str,
    analysis_result: TranscriptAnalysisResult,
    process_job_id: int | None = None,
    idempotency_key: str | None = None,
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
        idempotency_key=idempotency_key,
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
    idempotency_key: str | None = None,
) -> Job:
    """Enqueue session interpretation for a known persisted analysis run."""
    return store.enqueue(
        **interpret_session_job_spec(
            transcript_id=transcript_id,
            session_id=session_id,
            analysis_run_id=analysis_run_id,
            process_job_id=process_job_id,
            analyzed_through_entry_id=analyzed_through_entry_id,
            analyzed_through_byte_offset=analyzed_through_byte_offset,
            activity_count=activity_count,
            episode_count=episode_count,
            manifest_count=manifest_count,
            idempotency_key=idempotency_key,
        ).model_dump(),
    )
