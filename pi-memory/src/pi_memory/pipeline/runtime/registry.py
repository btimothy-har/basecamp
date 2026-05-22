"""Production job registry assembly for memory pipeline stages."""

from __future__ import annotations

from pi_memory.infra.job_runner import BaseJob, JobRegistry
from pi_memory.pipeline.runtime.adapters import PipelineAdapters
from pi_memory.pipeline.stages.assess_interpretation_quality.job import AssessInterpretationQualityJob
from pi_memory.pipeline.stages.interpret_session.job import InterpretSessionJob
from pi_memory.pipeline.stages.process_transcript.job import ProcessTranscriptJob
from pi_memory.pipeline.stages.project_memory_records.job import ProjectMemoryRecordsJob
from pi_memory.pipeline.stages.promote_durable_memory.job import PromoteDurableMemoryJob
from pi_memory.pipeline.stages.summarize_tool_activities.job import SummarizeToolActivitiesJob


def create_job_registry(adapters: PipelineAdapters | None = None) -> JobRegistry:
    """Create the production registry for executable pipeline jobs."""
    pipeline_adapters = PipelineAdapters() if adapters is None else adapters
    return JobRegistry(_stage_jobs(pipeline_adapters))


def _stage_jobs(adapters: PipelineAdapters) -> tuple[BaseJob, ...]:
    return (
        ProcessTranscriptJob(),
        SummarizeToolActivitiesJob(adapters),
        InterpretSessionJob(adapters),
        AssessInterpretationQualityJob(adapters),
        ProjectMemoryRecordsJob(adapters),
        PromoteDurableMemoryJob(adapters),
    )
