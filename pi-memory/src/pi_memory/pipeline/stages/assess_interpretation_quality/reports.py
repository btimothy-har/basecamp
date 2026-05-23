"""Quality report persistence helpers for the memory pipeline."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pi_memory.db.models import (
    Job,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
)
from pi_memory.pipeline.utils.metadata import safe_model_metadata
from pi_memory.quality import QualityReportDraft


def replace_quality_report(
    *,
    session: Session,
    job: Job,
    snapshot: SessionInterpretationSnapshot,
    draft: QualityReportDraft,
) -> SessionInterpretationQualityReport:
    existing = session.scalar(
        select(SessionInterpretationQualityReport).where(
            SessionInterpretationQualityReport.snapshot_id == snapshot.id,
        ),
    )
    if existing is not None:
        session.delete(existing)
        session.flush()

    report = SessionInterpretationQualityReport(
        snapshot_id=snapshot.id,
        job_id=job.id,
        quality_status=draft.quality_status,
        quality_reason=draft.quality_reason,
        derivation_status=draft.derivation_status,
        deterministic_status=draft.deterministic_status,
        semantic_status=draft.semantic_status,
        promotable=draft.promotable,
        deterministic_findings_json=draft.deterministic_findings_json,
        semantic_findings_json=draft.semantic_findings_json,
        claim_assessments_json=draft.claim_assessments_json,
        missing_high_signal_items_json=draft.missing_high_signal_items_json,
        model_metadata_json=draft.model_metadata_json,
        assessment_metadata_json=draft.assessment_metadata_json,
        prompt_version=draft.prompt_version,
        schema_version=draft.schema_version,
    )
    session.add(report)
    session.flush()
    session.refresh(report)
    return report


def quality_report_result_json(
    snapshot: SessionInterpretationSnapshot,
    report: SessionInterpretationQualityReport,
) -> dict[str, Any]:
    return {
        "status": "completed",
        "snapshot_id": snapshot.id,
        "quality_report_id": report.id,
        "session_id": snapshot.session.session_id,
        "session_row_id": snapshot.session_id,
        "transcript_id": snapshot.transcript_id,
        "analysis_run_id": snapshot.analysis_run_id,
        "quality_status": report.quality_status,
        "quality_reason": report.quality_reason,
        "derivation_status": report.derivation_status,
        "deterministic_status": report.deterministic_status,
        "semantic_status": report.semantic_status,
        "promotable": report.promotable,
        "prompt_version": report.prompt_version,
        "schema_version": report.schema_version,
        "model_metadata": safe_model_metadata(report.model_metadata_json),
    }
