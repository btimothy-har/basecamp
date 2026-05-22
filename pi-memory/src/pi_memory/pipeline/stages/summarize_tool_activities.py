"""Tool activity summarization pipeline stage."""

from __future__ import annotations

from typing import Any

from pi_memory.db import JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES, Job
from pi_memory.infra.job_queue import enqueue_interpret_session_job_for_analysis
from pi_memory.infra.job_runner import JobExecutionContext
from pi_memory.pipeline import payloads
from pi_memory.pipeline.freshness import is_stale_analysis_run, is_stale_process_job
from pi_memory.pipeline.services import PipelineServices
from pi_memory.pipeline.tool_activity import (
    apply_tool_summary_outcomes,
    summarize_tool_activity_work,
    tool_activity_summary_context,
    tool_summary_result_json,
    tool_summary_stale_result_json,
)


class SummarizeToolActivitiesJob:
    """Summarize tool-pair activities before session interpretation."""

    kind = JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES

    def __init__(self, services: PipelineServices) -> None:
        self._services = services

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

        outcomes = summarize_tool_activity_work(
            self._services.tool_activity_summarizer(),
            summary_context.work_items,
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
        )
        result_json["interpret_session_job_id"] = interpret_job.id
        return result_json
