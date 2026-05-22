"""Production job registry assembly for memory pipeline stages."""

from __future__ import annotations

from pi_memory.infra.job_runner import BaseJob, JobRegistry
from pi_memory.pipeline.services import PipelineServices


def create_job_registry(services: PipelineServices | None = None) -> JobRegistry:
    """Create the production registry for executable pipeline jobs."""
    pipeline_services = PipelineServices() if services is None else services
    return JobRegistry(_stage_jobs(pipeline_services))


def _stage_jobs(_services: PipelineServices) -> tuple[BaseJob, ...]:
    return ()
