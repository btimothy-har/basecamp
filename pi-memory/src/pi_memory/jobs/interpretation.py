"""Job enqueue helpers for session interpretation."""

from __future__ import annotations

from pi_memory.analysis import TranscriptAnalysisResult
from pi_memory.db import (
    JOB_KIND_ASSESS_INTERPRETATION_QUALITY,
    JOB_KIND_INTERPRET_SESSION,
    JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES,
    Job,
)
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


def enqueue_summarize_tool_activities_job(
    store: JobStore,
    *,
    transcript_id: int,
    session_id: str,
    analysis_result: TranscriptAnalysisResult,
    process_job_id: int | None = None,
) -> Job:
    """Enqueue tool activity summarization after a successful Phase 5A analysis."""
    return store.enqueue(
        JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES,
        payload_json=_analysis_job_payload(
            transcript_id=transcript_id,
            session_id=session_id,
            analysis_run_id=analysis_result.analysis_run_id,
            process_job_id=process_job_id,
            analyzed_through_entry_id=analysis_result.analyzed_through_entry_id,
            analyzed_through_byte_offset=analysis_result.analyzed_through_byte_offset,
            activity_count=analysis_result.activity_count,
            episode_count=analysis_result.episode_count,
            manifest_count=analysis_result.manifest_count,
        ),
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
        payload_json=_analysis_job_payload(
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


def _analysis_job_payload(
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
) -> dict[str, object]:
    return {
        "transcript_id": transcript_id,
        "analysis_run_id": analysis_run_id,
        # Remaining fields are audit/debug context for inspecting queued work.
        # Runners use SQLite as truth and only require ids/freshness tokens.
        "session_id": session_id,
        "process_job_id": process_job_id,
        "analyzed_through_entry_id": analyzed_through_entry_id,
        "analyzed_through_byte_offset": analyzed_through_byte_offset,
        "activity_count": activity_count,
        "episode_count": episode_count,
        "manifest_count": manifest_count,
    }
