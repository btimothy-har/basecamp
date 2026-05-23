"""Read-only quality report inspection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select

from pi_memory.db.constants import (
    SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
    SESSION_INTERPRETATION_DERIVATION_STATUSES,
    SESSION_INTERPRETATION_QUALITY_STATUS_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_QUALITY_STATUSES,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED,
)
from pi_memory.db.database import (
    Database,
    database,
)
from pi_memory.db.models import (
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
)

ASSESSMENT_STATE_COMPLETE = "complete"
ASSESSMENT_STATE_FAILED = "failed"
ASSESSMENT_STATE_PENDING = "pending"
ASSESSMENT_STATE_SKIPPED = "skipped"


@dataclass(frozen=True)
class QualityReportListResult:
    """Paginated quality report inspection result."""

    results: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
    query: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "query": dict(self.query),
            "pagination": {
                "total": self.total,
                "returned": len(self.results),
                "limit": self.limit,
                "offset": self.offset,
            },
            "results": list(self.results),
        }


class QualityReportFilterError(ValueError):
    """Raised when quality report filters are invalid."""

    @classmethod
    def invalid_quality_status(cls, value: str) -> QualityReportFilterError:
        return cls(f"Invalid quality_status: {value}")

    @classmethod
    def invalid_derivation_status(cls, value: str) -> QualityReportFilterError:
        return cls(f"Invalid derivation_status: {value}")

    @classmethod
    def invalid_limit(cls) -> QualityReportFilterError:
        return cls("limit must be between 1 and 100")

    @classmethod
    def invalid_offset(cls) -> QualityReportFilterError:
        return cls("offset must be non-negative")


class SessionQualityReportInspectionService:
    """Inspect persisted interpretation quality reports."""

    def __init__(self, database: Database = database) -> None:
        self._database = database

    def get_by_session_id(self, session_id: str) -> dict[str, Any] | None:
        """Return a safe quality report payload for a stable Pi session id."""
        self._database.initialize()
        with self._database.session() as db_session:
            row = db_session.execute(
                _quality_report_rows()
                .where(MemorySession.session_id == session_id)
                .order_by(SessionInterpretationQualityReport.updated_at.desc())
                .limit(1),
            ).one_or_none()
            if row is None:
                return None
            report, snapshot, memory_session = row
            return serialize_quality_report(report, snapshot=snapshot, memory_session=memory_session)

    def list_reports(
        self,
        *,
        quality_status: str | None = None,
        derivation_status: str | None = None,
        promotable: bool | None = None,
        is_current: bool | None = None,
        cwd: str | None = None,
        worktree_label: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> QualityReportListResult:
        """Return quality reports with optional filters and pagination."""
        _validate_filters(
            quality_status=quality_status,
            derivation_status=derivation_status,
            limit=limit,
            offset=offset,
        )
        self._database.initialize()
        query_values = _query_payload(
            quality_status=quality_status,
            derivation_status=derivation_status,
            promotable=promotable,
            is_current=is_current,
            cwd=cwd,
            worktree_label=worktree_label,
            limit=limit,
            offset=offset,
        )
        with self._database.session() as db_session:
            filtered = _apply_filters(
                _quality_report_rows(),
                quality_status=quality_status,
                derivation_status=derivation_status,
                promotable=promotable,
                is_current=is_current,
                cwd=cwd,
                worktree_label=worktree_label,
            )
            count_query = _apply_filters(
                select(func.count()).select_from(SessionInterpretationQualityReport),
                quality_status=quality_status,
                derivation_status=derivation_status,
                promotable=promotable,
                is_current=is_current,
                cwd=cwd,
                worktree_label=worktree_label,
                include_joins=True,
            )
            total = int(db_session.scalar(count_query) or 0)
            rows = db_session.execute(
                filtered.order_by(SessionInterpretationQualityReport.updated_at.desc()).offset(offset).limit(limit),
            ).all()
        return QualityReportListResult(
            results=[
                serialize_quality_report(report, snapshot=snapshot, memory_session=memory_session)
                for report, snapshot, memory_session in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
            query=query_values,
        )

    def sample_reports(
        self,
        *,
        count: int = 5,
        quality_status: str | None = None,
        derivation_status: str | None = None,
        promotable: bool | None = None,
        is_current: bool | None = None,
        cwd: str | None = None,
        worktree_label: str | None = None,
    ) -> dict[str, Any]:
        """Return a bounded random sample of quality reports."""
        _validate_filters(quality_status=quality_status, derivation_status=derivation_status, limit=count, offset=0)
        self._database.initialize()
        with self._database.session() as db_session:
            rows = db_session.execute(
                _apply_filters(
                    _quality_report_rows(),
                    quality_status=quality_status,
                    derivation_status=derivation_status,
                    promotable=promotable,
                    is_current=is_current,
                    cwd=cwd,
                    worktree_label=worktree_label,
                )
                .order_by(func.random())
                .limit(count),
            ).all()
        return {
            "count": len(rows),
            "query": _query_payload(
                quality_status=quality_status,
                derivation_status=derivation_status,
                promotable=promotable,
                is_current=is_current,
                cwd=cwd,
                worktree_label=worktree_label,
                limit=count,
                offset=0,
            ),
            "results": [
                serialize_quality_report(report, snapshot=snapshot, memory_session=memory_session)
                for report, snapshot, memory_session in rows
            ],
        }


def serialize_quality_report(
    report: SessionInterpretationQualityReport,
    *,
    snapshot: SessionInterpretationSnapshot,
    memory_session: MemorySession,
) -> dict[str, Any]:
    """Return a JSON-safe quality report payload without raw transcript rows."""
    deterministic_findings = list(report.deterministic_findings_json)
    semantic_findings = list(report.semantic_findings_json)
    return {
        "session_id": memory_session.session_id,
        "session_row_id": memory_session.id,
        "session_metadata": {
            "cwd": memory_session.cwd,
            "worktree_label": memory_session.worktree_label,
            "worktree_path": memory_session.worktree_path,
        },
        "quality_report_id": report.id,
        "snapshot_id": report.snapshot_id,
        "snapshot_status": snapshot.status,
        "transcript_id": snapshot.transcript_id,
        "analysis_run_id": snapshot.analysis_run_id,
        "job_id": report.job_id,
        "quality_status": report.quality_status,
        "quality_reason": report.quality_reason,
        "assessment_state": _assessment_state(report, snapshot),
        "derivation_status": report.derivation_status,
        "is_current": report.derivation_status == SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
        "deterministic_status": report.deterministic_status,
        "semantic_status": report.semantic_status,
        "promotable": report.promotable,
        "finding_counts": _finding_counts(deterministic_findings, semantic_findings),
        "deterministic_findings": deterministic_findings,
        "semantic_findings": semantic_findings,
        "claim_assessments": list(report.claim_assessments_json),
        "missing_high_signal_items": list(report.missing_high_signal_items_json),
        "episode_interpretation": _episode_interpretation_coverage(snapshot),
        "model_metadata": dict(report.model_metadata_json),
        "assessment_metadata": dict(report.assessment_metadata_json),
        "prompt_version": report.prompt_version,
        "schema_version": report.schema_version,
        "created_at": _serialize_datetime(report.created_at),
        "updated_at": _serialize_datetime(report.updated_at),
    }


def _episode_interpretation_coverage(snapshot: SessionInterpretationSnapshot) -> dict[str, Any]:
    interpretation = snapshot.interpretation_json if isinstance(snapshot.interpretation_json, dict) else {}
    coverage = interpretation.get("aggregation")
    return dict(coverage) if isinstance(coverage, dict) else {}


def _quality_report_rows() -> Select[
    tuple[SessionInterpretationQualityReport, SessionInterpretationSnapshot, MemorySession]
]:
    return (
        select(SessionInterpretationQualityReport, SessionInterpretationSnapshot, MemorySession)
        .join(
            SessionInterpretationSnapshot,
            SessionInterpretationQualityReport.snapshot_id == SessionInterpretationSnapshot.id,
        )
        .join(MemorySession, SessionInterpretationSnapshot.session_id == MemorySession.id)
    )


def _apply_filters(
    query: Select,
    *,
    quality_status: str | None,
    derivation_status: str | None,
    promotable: bool | None,
    is_current: bool | None,
    cwd: str | None,
    worktree_label: str | None,
    include_joins: bool = False,
) -> Select:
    if include_joins:
        query = query.join(
            SessionInterpretationSnapshot,
            SessionInterpretationQualityReport.snapshot_id == SessionInterpretationSnapshot.id,
        ).join(MemorySession, SessionInterpretationSnapshot.session_id == MemorySession.id)
    if quality_status is not None:
        query = query.where(SessionInterpretationQualityReport.quality_status == quality_status)
    if derivation_status is not None:
        query = query.where(SessionInterpretationQualityReport.derivation_status == derivation_status)
    if promotable is not None:
        query = query.where(SessionInterpretationQualityReport.promotable == promotable)
    if is_current is not None:
        expected = SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT if is_current else None
        if expected is None:
            query = query.where(
                SessionInterpretationQualityReport.derivation_status
                != SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
            )
        else:
            query = query.where(SessionInterpretationQualityReport.derivation_status == expected)
    if cwd is not None:
        query = query.where(MemorySession.cwd == cwd)
    if worktree_label is not None:
        query = query.where(MemorySession.worktree_label == worktree_label)
    return query


def _validate_filters(
    *,
    quality_status: str | None,
    derivation_status: str | None,
    limit: int,
    offset: int,
) -> None:
    if quality_status is not None and quality_status not in SESSION_INTERPRETATION_QUALITY_STATUSES:
        raise QualityReportFilterError.invalid_quality_status(quality_status)
    if derivation_status is not None and derivation_status not in SESSION_INTERPRETATION_DERIVATION_STATUSES:
        raise QualityReportFilterError.invalid_derivation_status(derivation_status)
    if not 1 <= limit <= 100:
        raise QualityReportFilterError.invalid_limit()
    if offset < 0:
        raise QualityReportFilterError.invalid_offset()


def _query_payload(**values: Any) -> dict[str, Any]:
    return dict(values)


def _assessment_state(report: SessionInterpretationQualityReport, snapshot: SessionInterpretationSnapshot) -> str:
    if (
        report.quality_status == SESSION_INTERPRETATION_QUALITY_STATUS_ASSESSMENT_FAILED
        or report.semantic_status == SESSION_INTERPRETATION_SEMANTIC_STATUS_ASSESSMENT_FAILED
    ):
        return ASSESSMENT_STATE_FAILED
    if report.semantic_status == SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED:
        return ASSESSMENT_STATE_SKIPPED if snapshot.status != "completed" else ASSESSMENT_STATE_PENDING
    return ASSESSMENT_STATE_COMPLETE


def _finding_counts(*finding_groups: list[Any]) -> dict[str, int]:
    counts = {"critical": 0, "warning": 0, "info": 0}
    for findings in finding_groups:
        for finding in findings:
            if isinstance(finding, dict):
                severity = finding.get("severity")
                if severity in counts:
                    counts[severity] += 1
    return counts


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
