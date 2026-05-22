"""Memory projection pipeline stage."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from pi_memory.db import (
    JOB_KIND_PROJECT_MEMORY_RECORDS,
    DurableMemoryItem,
    Job,
    MemoryProjectionRecord,
    SessionInterpretationQualityReport,
)
from pi_memory.durable import DurableMemoryProjectionError
from pi_memory.infra.job_runner import JobExecutionContext
from pi_memory.pipeline import payloads
from pi_memory.pipeline.errors import MemoryProjectionJobError
from pi_memory.pipeline.projection_records import (
    deleted_projection_record_count,
    indexed_projection_record_count,
    project_durable_memory_record_outcome,
)
from pi_memory.pipeline.services import PipelineServices
from pi_memory.projection import project_session_claims


class ProjectMemoryRecordsJob:
    """Project session claims and durable memories into memory records."""

    kind = JOB_KIND_PROJECT_MEMORY_RECORDS

    def __init__(self, services: PipelineServices) -> None:
        self._services = services

    def run(self, context: JobExecutionContext, job: Job) -> dict[str, Any]:
        scope = payloads.memory_projection_scope(job.payload_json)
        context.database.initialize()
        if scope == "quality_report":
            return self._project_quality_report_memory_records(context, job)
        return self._rebuild_memory_projection(context)

    def _project_quality_report_memory_records(self, context: JobExecutionContext, job: Job) -> dict[str, Any]:
        quality_report_id = payloads.quality_report_id(job.payload_json)
        with context.database.session() as session:
            result = project_session_claims(session, quality_report_id, self._services.memory_projection())
            result_json = {
                "status": "completed",
                "scope": "quality_report",
                "quality_report_id": result.report_id,
                "snapshot_id": result.snapshot_id,
                "eligible": result.eligible,
                "indexed_count": result.indexed_count,
                "skipped_count": result.skipped_count,
                "deleted_count": result.deleted_count,
                "failed_count": result.failed_count,
                "reason": result.reason,
            }
        if result.failed_count > 0:
            raise MemoryProjectionJobError()
        return result_json

    def _rebuild_memory_projection(self, context: JobExecutionContext) -> dict[str, Any]:
        durable_error: DurableMemoryProjectionError | None = None
        durable_failed_count = 0
        with context.database.session() as session:
            projection = self._services.memory_projection()
            reports = list(
                session.scalars(
                    select(SessionInterpretationQualityReport).order_by(SessionInterpretationQualityReport.id),
                ),
            )
            durable_memories = list(session.scalars(select(DurableMemoryItem).order_by(DurableMemoryItem.id)))
            report_results = [project_session_claims(session, report.id, projection) for report in reports]
            durable_records: list[MemoryProjectionRecord] = []
            for memory in durable_memories:
                record, error = project_durable_memory_record_outcome(session, memory, projection)
                if record is not None:
                    durable_records.append(record)
                    continue
                durable_failed_count += 1
                if durable_error is None:
                    durable_error = error
            result_json = {
                "status": "completed",
                "scope": "all",
                "quality_report_count": len(report_results),
                "durable_memory_count": len(durable_records) + durable_failed_count,
                "indexed_count": sum(result.indexed_count for result in report_results)
                + indexed_projection_record_count(durable_records),
                "skipped_count": sum(result.skipped_count for result in report_results),
                "deleted_count": sum(result.deleted_count for result in report_results)
                + deleted_projection_record_count(durable_records),
                "failed_count": sum(result.failed_count for result in report_results) + durable_failed_count,
            }
        if durable_error is not None:
            raise durable_error
        if result_json["failed_count"] > 0:
            raise MemoryProjectionJobError()
        return result_json
