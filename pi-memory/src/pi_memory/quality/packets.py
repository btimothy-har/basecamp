"""Bounded quality assessment packet builders."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pi_memory.db import ActivityUnit, MemorySession, SessionInterpretationSnapshot
from pi_memory.interpretation.packets import BoundedText
from pi_memory.quality.contracts import (
    DERIVATION_STATUS_CURRENT,
    DETERMINISTIC_STATUS_PASSED,
    SEMANTIC_STATUS_NOT_ASSESSED,
    QualityFinding,
    QualityReportDraft,
)
from pi_memory.quality.deterministic import assess_deterministic_interpretation_quality

QUALITY_ACTIVITY_TEXT_CHAR_LIMIT = 800
QUALITY_INTERPRETATION_TEXT_CHAR_LIMIT = 1_200
QUALITY_METADATA_CHAR_LIMIT = 300
QUALITY_MAX_ACTIVITIES = 120
QUALITY_MAX_CITATIONS = 160
QUALITY_MAX_CLAIMS = 80


@dataclass(frozen=True)
class QualityActivityContext:
    """Bounded chronological activity text for semantic quality assessment."""

    activity_unit_id: int
    ordinal: int
    kind: str
    source_origin: str
    activity_text_kind: str
    activity_text_status: str
    byte_start: int
    byte_end: int
    source_ref_ids: tuple[str, ...]
    activity_text: BoundedText | None


@dataclass(frozen=True)
class QualityPacketReadiness:
    """Semantic quality readiness derived from deterministic quality state."""

    snapshot_id: int
    snapshot_status: str
    derivation_status: str
    deterministic_status: str
    quality_status: str
    quality_reason: str | None
    semantic_status: str
    can_assess_semantically: bool
    blocked_reason: str | None
    deterministic_findings: tuple[QualityFinding, ...]


@dataclass(frozen=True)
class QualityPacket:
    """Bounded semantic assessment input for one interpretation snapshot."""

    snapshot_id: int
    session_metadata: Mapping[str, Any]
    snapshot_metadata: Mapping[str, Any]
    readiness: QualityPacketReadiness
    interpretation: Mapping[str, Any]
    citations: tuple[Mapping[str, Any], ...]
    activities: tuple[QualityActivityContext, ...]
    omitted_activity_count: int
    deterministic_report: QualityReportDraft

    @property
    def claim_count(self) -> int:
        claims = self.interpretation.get("claims")
        return len(claims) if isinstance(claims, list) else 0

    @property
    def source_ref_ids(self) -> frozenset[str]:
        ids: set[str] = set()
        for citation in self.citations:
            source_ref_id = citation.get("source_ref_id")
            if isinstance(source_ref_id, str):
                ids.add(source_ref_id)
        for activity in self.activities:
            ids.update(activity.source_ref_ids)
        return frozenset(ids)


def build_quality_packet(
    session: Session,
    snapshot: SessionInterpretationSnapshot,
    deterministic_report: QualityReportDraft | None = None,
) -> QualityPacket:
    """Build a bounded semantic quality packet without raw transcript rows."""
    report = deterministic_report or assess_deterministic_interpretation_quality(session, snapshot)
    stable_session = _stable_session_id(session, snapshot.session_id)
    activities, omitted_activity_count = _activity_contexts(session, snapshot)
    citations = tuple(_bounded_json(citation) for citation in _citation_rows(snapshot)[:QUALITY_MAX_CITATIONS])
    return QualityPacket(
        snapshot_id=snapshot.id,
        session_metadata={
            "session_row_id": snapshot.session_id,
            "stable_session_id": stable_session,
        },
        snapshot_metadata={
            "snapshot_id": snapshot.id,
            "transcript_id": snapshot.transcript_id,
            "analysis_run_id": snapshot.analysis_run_id,
            "analyzed_through_entry_id": snapshot.analyzed_through_entry_id,
            "analyzed_through_byte_offset": snapshot.analyzed_through_byte_offset,
            "origin_counts": _bounded_json(snapshot.origin_counts_json or {}),
            "claim_source_activity_count": snapshot.claim_source_activity_count,
            "prompt_version": snapshot.prompt_version,
            "schema_version": snapshot.schema_version,
        },
        readiness=QualityPacketReadiness(
            snapshot_id=snapshot.id,
            snapshot_status=snapshot.status,
            derivation_status=report.derivation_status,
            deterministic_status=report.deterministic_status,
            quality_status=report.quality_status,
            quality_reason=report.quality_reason,
            semantic_status=report.semantic_status,
            can_assess_semantically=_can_assess_semantically(snapshot, report),
            blocked_reason=snapshot.blocked_reason,
            deterministic_findings=tuple(report.deterministic_findings),
        ),
        interpretation=_interpretation_prompt_data(snapshot.interpretation_json),
        citations=citations,
        activities=activities,
        omitted_activity_count=omitted_activity_count,
        deterministic_report=report,
    )


def quality_packet_prompt_data(packet: QualityPacket) -> Mapping[str, Any]:
    """Return JSON-safe prompt data for semantic quality assessment."""
    return {
        "session": dict(packet.session_metadata),
        "snapshot": dict(packet.snapshot_metadata),
        "readiness": _readiness_prompt_data(packet.readiness),
        "interpretation": dict(packet.interpretation),
        "citations": [dict(citation) for citation in packet.citations],
        "activities": [_activity_prompt_data(activity) for activity in packet.activities],
        "activity_bounds": {
            "included_activity_count": len(packet.activities),
            "omitted_activity_count": packet.omitted_activity_count,
            "activity_text_char_limit": QUALITY_ACTIVITY_TEXT_CHAR_LIMIT,
        },
    }


def _stable_session_id(session: Session, session_row_id: int) -> str:
    memory_session = session.get(MemorySession, session_row_id)
    return memory_session.session_id if memory_session is not None else ""


def _can_assess_semantically(snapshot: SessionInterpretationSnapshot, report: QualityReportDraft) -> bool:
    return (
        snapshot.status == "completed"
        and report.derivation_status == DERIVATION_STATUS_CURRENT
        and report.deterministic_status == DETERMINISTIC_STATUS_PASSED
        and report.semantic_status == SEMANTIC_STATUS_NOT_ASSESSED
    )


def _interpretation_prompt_data(value: Any) -> Mapping[str, Any]:
    interpretation = _bounded_json(
        value if isinstance(value, Mapping) else {},
        string_limit=QUALITY_INTERPRETATION_TEXT_CHAR_LIMIT,
    )
    if not isinstance(interpretation, Mapping):
        return {}
    claims = interpretation.get("claims")
    if isinstance(claims, list) and len(claims) > QUALITY_MAX_CLAIMS:
        interpretation = dict(interpretation)
        interpretation["claims"] = claims[:QUALITY_MAX_CLAIMS]
        interpretation["omitted_claim_count"] = len(claims) - QUALITY_MAX_CLAIMS
    return interpretation


def _citation_rows(snapshot: SessionInterpretationSnapshot) -> list[Mapping[str, Any]]:
    if not isinstance(snapshot.citations_json, list):
        return []
    return [citation for citation in snapshot.citations_json if isinstance(citation, Mapping)]


def _activity_contexts(
    session: Session,
    snapshot: SessionInterpretationSnapshot,
) -> tuple[tuple[QualityActivityContext, ...], int]:
    if snapshot.analysis_run_id is None:
        return (), 0
    citation_source_refs = _source_refs_by_activity_id(snapshot)
    units = list(
        session.scalars(
            select(ActivityUnit)
            .where(ActivityUnit.analysis_run_id == snapshot.analysis_run_id)
            .order_by(ActivityUnit.ordinal, ActivityUnit.id),
        ),
    )
    contexts = tuple(
        _activity_context(unit, citation_source_refs.get(unit.id, ())) for unit in units[:QUALITY_MAX_ACTIVITIES]
    )
    return contexts, max(len(units) - len(contexts), 0)


def _source_refs_by_activity_id(snapshot: SessionInterpretationSnapshot) -> dict[int, tuple[str, ...]]:
    refs: dict[int, list[str]] = {}
    for citation in _citation_rows(snapshot):
        activity_unit_id = citation.get("activity_unit_id")
        source_ref_id = citation.get("source_ref_id")
        if isinstance(activity_unit_id, int) and isinstance(source_ref_id, str):
            refs.setdefault(activity_unit_id, []).append(source_ref_id)
    return {activity_id: tuple(dict.fromkeys(values)) for activity_id, values in refs.items()}


def _activity_context(unit: ActivityUnit, source_ref_ids: tuple[str, ...]) -> QualityActivityContext:
    return QualityActivityContext(
        activity_unit_id=unit.id,
        ordinal=unit.ordinal,
        kind=unit.kind,
        source_origin=unit.source_origin,
        activity_text_kind=unit.activity_text_kind,
        activity_text_status=unit.activity_text_status,
        byte_start=unit.byte_start,
        byte_end=unit.byte_end,
        source_ref_ids=source_ref_ids,
        activity_text=_bounded_text(unit.activity_text, QUALITY_ACTIVITY_TEXT_CHAR_LIMIT)
        if unit.activity_text is not None
        else None,
    )


def _readiness_prompt_data(readiness: QualityPacketReadiness) -> Mapping[str, Any]:
    return {
        "snapshot_id": readiness.snapshot_id,
        "snapshot_status": readiness.snapshot_status,
        "derivation_status": readiness.derivation_status,
        "deterministic_status": readiness.deterministic_status,
        "quality_status": readiness.quality_status,
        "quality_reason": readiness.quality_reason,
        "semantic_status": readiness.semantic_status,
        "can_assess_semantically": readiness.can_assess_semantically,
        "blocked_reason": readiness.blocked_reason,
        "deterministic_findings": [finding.model_dump(mode="json") for finding in readiness.deterministic_findings],
    }


def _activity_prompt_data(activity: QualityActivityContext) -> Mapping[str, Any]:
    return {
        "activity_unit_id": activity.activity_unit_id,
        "ordinal": activity.ordinal,
        "kind": activity.kind,
        "source_origin": activity.source_origin,
        "activity_text_kind": activity.activity_text_kind,
        "activity_text_status": activity.activity_text_status,
        "byte_start": activity.byte_start,
        "byte_end": activity.byte_end,
        "source_ref_ids": list(activity.source_ref_ids),
        "activity_text": _bounded_text_prompt_data(activity.activity_text)
        if activity.activity_text is not None
        else None,
    }


def _bounded_text(value: str, limit: int) -> BoundedText:
    text = value[:limit]
    original_bytes = len(value.encode("utf-8"))
    text_bytes = len(text.encode("utf-8"))
    return BoundedText(
        text=text,
        original_char_count=len(value),
        original_byte_count=original_bytes,
        is_truncated=len(value) > limit,
        omitted_char_count=max(len(value) - len(text), 0),
        omitted_byte_count=max(original_bytes - text_bytes, 0),
    )


def _bounded_text_prompt_data(value: BoundedText) -> Mapping[str, Any]:
    return {
        "text": value.text,
        "original_char_count": value.original_char_count,
        "original_byte_count": value.original_byte_count,
        "is_truncated": value.is_truncated,
        "omitted_char_count": value.omitted_char_count,
        "omitted_byte_count": value.omitted_byte_count,
    }


def _bounded_json(value: Any, *, string_limit: int = QUALITY_METADATA_CHAR_LIMIT) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _bounded_json(value[key], string_limit=string_limit) for key in sorted(value, key=str)}
    if isinstance(value, tuple | list):
        return [_bounded_json(item, string_limit=string_limit) for item in value]
    if isinstance(value, str):
        return _bounded_metadata_string(value, string_limit)
    if value is None or isinstance(value, bool | int | float):
        return value
    return _bounded_metadata_string(str(value), string_limit)


def _bounded_metadata_string(value: str, limit: int) -> str | Mapping[str, Any]:
    if len(value) <= limit:
        return value
    return {
        "omitted": True,
        "char_count": len(value),
        "byte_count": len(value.encode("utf-8")),
    }
