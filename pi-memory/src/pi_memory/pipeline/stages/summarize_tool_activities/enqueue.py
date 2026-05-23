"""Queue input contract for tool activity summarization jobs."""

from __future__ import annotations

from pi_memory.analysis import TranscriptAnalysisResult
from pi_memory.constants import JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES
from pi_memory.db.models import Job
from pi_memory.infra.job_queue.store import JobStore
from pi_memory.pipeline.utils import payloads


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
        payload_json=payloads.analysis_job_payload(
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
