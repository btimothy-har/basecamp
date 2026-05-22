"""Production job registry assembly for memory pipeline stages."""

from __future__ import annotations

from pi_memory.infra.job_runner import BaseJob, JobRegistry
from pi_memory.pipeline.services import PipelineServices
from pi_memory.pipeline.stages.interpret_session import InterpretSessionJob
from pi_memory.pipeline.stages.process_transcript import ProcessTranscriptJob
from pi_memory.pipeline.stages.summarize_tool_activities import SummarizeToolActivitiesJob


def create_job_registry(services: PipelineServices | None = None) -> JobRegistry:
    """Create the production registry for executable pipeline jobs."""
    pipeline_services = PipelineServices() if services is None else services
    return JobRegistry(_stage_jobs(pipeline_services))


def _stage_jobs(services: PipelineServices) -> tuple[BaseJob, ...]:
    return (
        ProcessTranscriptJob(),
        SummarizeToolActivitiesJob(services),
        InterpretSessionJob(services),
    )
