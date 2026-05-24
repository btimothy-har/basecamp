"""Tool activity summarization pipeline stage."""

from __future__ import annotations

from typing import Any

from pi_memory.constants import JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES
from pi_memory.db.models import Job
from pi_memory.infra.job_runner import JobExecutionContext
from pi_memory.pipeline.runtime.adapters import PipelineAdapters
from pi_memory.pipeline.stages.interpret_session.enqueue import (
    enqueue_interpret_session_job_for_analysis,
    interpret_session_idempotency_key,
)
from pi_memory.pipeline.stages.summarize_tool_activities.summaries import (
    apply_tool_summary_outcomes,
    summarize_tool_activity_work,
    tool_activity_summary_context,
    tool_summary_result_json,
    tool_summary_stale_result_json,
)
from pi_memory.pipeline.utils import payloads
from pi_memory.pipeline.utils.freshness import is_stale_analysis_run, is_stale_process_job


class SummarizeToolActivitiesJob:
    """Summarize tool-pair activities before session interpretation."""

    kind = JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES

    def __init__(self, adapters: PipelineAdapters) -> None:
        self._adapters = adapters

    def run(self, context: JobExecutionContext, job: Job) -> dict[str, Any]:
        transcript_id, analysis_run_id, process_job_id = payloads.summarize_tool_activities(job.payload_json)
        context.database.initialize()
        with context.database.session() as session:
            summary_context = tool_activity_summary_context(
                session=session,
                transcript_id=transcript_id,
                analysis_run_id=analysis_run_id,
                process_job_id=process_job_id,
            )
            if summary_context is None:
                return tool_summary_stale_result_json(
                    transcript_id=transcript_id,
                    analysis_run_id=analysis_run_id,
                    process_job_id=process_job_id,
                )

        outcomes = (
            summarize_tool_activity_work(
                self._adapters.tool_activity_summarizer(),
                summary_context.work_items,
            )
            if summary_context.work_items
            else []
        )
        with context.database.session() as session:
            if is_stale_analysis_run(session, transcript_id, analysis_run_id) or is_stale_process_job(
                session,
                transcript_id,
                process_job_id,
            ):
                return tool_summary_stale_result_json(
                    transcript_id=transcript_id,
                    analysis_run_id=analysis_run_id,
                    process_job_id=process_job_id,
                )
            apply_tool_summary_outcomes(session, outcomes)

        result_json = tool_summary_result_json(summary_context, outcomes)
        interpret_job = enqueue_interpret_session_job_for_analysis(
            context.store,
            transcript_id=summary_context.transcript_id,
            session_id=summary_context.session_id,
            analysis_run_id=summary_context.analysis_run_id,
            process_job_id=summary_context.process_job_id,
            analyzed_through_entry_id=summary_context.analyzed_through_entry_id,
            analyzed_through_byte_offset=summary_context.analyzed_through_byte_offset,
            activity_count=summary_context.activity_count,
            episode_count=summary_context.episode_count,
            manifest_count=summary_context.manifest_count,
            idempotency_key=interpret_session_idempotency_key(job.id),
        )
        result_json["interpret_session_job_id"] = interpret_job.id
        return result_json

