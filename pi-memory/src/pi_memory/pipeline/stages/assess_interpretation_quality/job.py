"""Interpretation quality assessment pipeline stage."""

from __future__ import annotations

from typing import Any

from pi_memory.db import (
    JOB_KIND_ASSESS_INTERPRETATION_QUALITY,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_PENDING,
    SESSION_INTERPRETATION_QUALITY_STATUS_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
    Job,
    SessionInterpretationSnapshot,
)
from pi_memory.infra.job_queue import enqueue_project_memory_records_job, enqueue_promote_durable_memory_job
from pi_memory.infra.job_runner import JobExecutionContext, PermanentJobError
from pi_memory.pipeline.runtime.adapters import PipelineAdapters
from pi_memory.pipeline.runtime.errors import InvalidJobPayloadError
from pi_memory.pipeline.stages.assess_interpretation_quality.reports import (
    quality_report_result_json,
    replace_quality_report,
)
from pi_memory.pipeline.utils import payloads
from pi_memory.quality import (
    QualityReportDraft,
    assess_deterministic_interpretation_quality,
    build_quality_packet,
)


class AssessInterpretationQualityJob:
    """Assess interpretation quality and enqueue downstream memory work."""

    kind = JOB_KIND_ASSESS_INTERPRETATION_QUALITY

    def __init__(self, adapters: PipelineAdapters) -> None:
        self._adapters = adapters

    def run(self, context: JobExecutionContext, job: Job) -> dict[str, Any]:
        try:
            return self._run(context, job)
        except PermanentJobError:
            raise
        except Exception as error:
            if not _is_final_quality_attempt(job):
                raise
            self._write_assessment_failed_quality_report(context, job, error_type=type(error).__name__)
            raise PermanentJobError(type(error).__name__) from error

    def _run(self, context: JobExecutionContext, job: Job) -> dict[str, Any]:
        snapshot_id = payloads.snapshot_id(job.payload_json)
        context.database.initialize()
        with context.database.session() as session:
            snapshot = session.get(SessionInterpretationSnapshot, snapshot_id)
            if snapshot is None:
                return {
                    "status": "stale",
                    "snapshot_id": snapshot_id,
                    "quality_report_id": None,
                    "stale_reason": "snapshot_not_found",
                }
            draft = assess_deterministic_interpretation_quality(session, snapshot)
            if (
                snapshot.status == SESSION_INTERPRETATION_STATUS_COMPLETED
                and draft.quality_reason == SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_PENDING
            ):
                packet = build_quality_packet(session, snapshot, deterministic_report=draft)
                draft = self._adapters.interpretation_quality_assessor().assess(packet)
            report = replace_quality_report(session=session, job=job, snapshot=snapshot, draft=draft)
            result_json = quality_report_result_json(snapshot, report)

        project_job = enqueue_project_memory_records_job(
            context.store,
            quality_report_id=result_json["quality_report_id"],
            session_id=result_json["session_id"],
            quality_job_id=job.id,
        )
        promote_job = enqueue_promote_durable_memory_job(
            context.store,
            quality_report_id=result_json["quality_report_id"],
            session_id=result_json["session_id"],
            quality_job_id=job.id,
        )
        result_json["project_memory_records_job_id"] = project_job.id
        result_json["promote_durable_memory_job_id"] = promote_job.id
        return result_json

    def _write_assessment_failed_quality_report(
        self,
        context: JobExecutionContext,
        job: Job,
        *,
        error_type: str,
    ) -> None:
        try:
            snapshot_id = payloads.snapshot_id(job.payload_json)
        except InvalidJobPayloadError:
            return
        context.database.initialize()
        with context.database.session() as session:
            snapshot = session.get(SessionInterpretationSnapshot, snapshot_id)
            if snapshot is None:
                return
            deterministic = assess_deterministic_interpretation_quality(session, snapshot)
            draft = QualityReportDraft(
                quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_ASSESSMENT_FAILED,
                quality_reason=SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_FAILED,
                derivation_status=deterministic.derivation_status,
                deterministic_status=deterministic.deterministic_status,
                semantic_status=SESSION_INTERPRETATION_SEMANTIC_STATUS_ASSESSMENT_FAILED,
                promotable=False,
                deterministic_findings=list(deterministic.deterministic_findings),
                assessment_metadata={
                    **deterministic.assessment_metadata,
                    "assessment_failed_error_type": error_type,
                },
            )
            replace_quality_report(session=session, job=job, snapshot=snapshot, draft=draft)


def _is_final_quality_attempt(job: Job) -> bool:
    return job.kind == JOB_KIND_ASSESS_INTERPRETATION_QUALITY and job.attempts >= job.max_attempts
