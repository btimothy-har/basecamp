"""Read-only bounded evidence packet builders for durable-memory promotion."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from pi_memory.db import (
    ActivityUnit,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
)
from pi_memory.durable.contracts import DurableMemoryCandidate, QualityEligibilityEnvelope
from pi_memory.durable.eligibility import evaluate_claim_eligibility

DURABLE_SOURCE_REF_LIMIT = 20
DURABLE_ACTIVITY_TEXT_CHAR_LIMIT = 1_000
DURABLE_METADATA_STRING_LIMIT = 400


class DurableMemoryPacketError(Exception):
    """Raised when durable-memory evidence cannot be built safely."""

    @classmethod
    def report_not_found(cls, report_id: int) -> DurableMemoryPacketError:
        return cls(f"Durable memory quality report not found: {report_id}")

    @classmethod
    def claim_missing(cls, snapshot_id: int, claim_index: int) -> DurableMemoryPacketError:
        return cls(f"Durable memory claim missing for snapshot {snapshot_id} claim_index {claim_index}")

    @classmethod
    def source_refs_missing(cls, snapshot_id: int, claim_index: int) -> DurableMemoryPacketError:
        return cls(f"Durable memory claim source refs missing for snapshot {snapshot_id} claim_index {claim_index}")

    @classmethod
    def claim_invalid(cls, snapshot_id: int, claim_index: int) -> DurableMemoryPacketError:
        return cls(f"Durable memory claim invalid for snapshot {snapshot_id} claim_index {claim_index}")


@dataclass(frozen=True)
class BoundedText:
    """Text bounded for provider/evaluator packets."""

    text: str
    original_char_count: int
    original_byte_count: int
    is_truncated: bool
    omitted_char_count: int
    omitted_byte_count: int


@dataclass(frozen=True)
class SourceRefEvidence:
    """Bounded evidence for one canonical interpretation source ref."""

    source_ref_id: str
    activity_unit_id: int | None
    source_origin: str | None
    activity_kind: str | None
    activity_ordinal: int | None
    episode_ordinal: int | None
    activity_text: BoundedText | None
    citation_metadata: Mapping[str, Any]


@dataclass(frozen=True)
class DurableMemoryEvidencePacket:
    """Read-only bounded evidence for durable-memory candidate evaluation."""

    session_id: str
    repo_name: str | None
    worktree_label: str | None
    snapshot_id: int
    quality_report_id: int
    candidate: DurableMemoryCandidate
    eligibility: QualityEligibilityEnvelope
    source_evidence: tuple[SourceRefEvidence, ...]
    omitted_source_count: int


def build_candidate_from_quality_report(
    report: SessionInterpretationQualityReport,
    claim_index: int,
) -> DurableMemoryCandidate:
    """Build a strict durable-memory candidate from a persisted quality report.

    Args:
        report: Persisted quality report with its interpretation snapshot.
        claim_index: Zero-based interpretation claim index.

    Returns:
        Strict durable-memory candidate contract.

    Raises:
        DurableMemoryPacketError: If the claim or source refs are missing/invalid.
    """
    claim = _claim_at(report.snapshot, claim_index)
    source_ref_ids = _source_ref_ids(claim)
    if not source_ref_ids:
        raise DurableMemoryPacketError.source_refs_missing(report.snapshot.id, claim_index)
    confidence = _float_value(claim.get("confidence"))
    if confidence is None:
        raise DurableMemoryPacketError.claim_invalid(report.snapshot.id, claim_index)
    try:
        return DurableMemoryCandidate(
            snapshot_id=report.snapshot.id,
            quality_report_id=report.id,
            claim_index=claim_index,
            claim_kind=_string_value(claim.get("kind")) or "",
            statement=_string_value(claim.get("statement")) or "",
            confidence=confidence,
            source_ref_ids=source_ref_ids,
            content_hash=_content_hash(claim),
        )
    except ValidationError as error:
        raise DurableMemoryPacketError.claim_invalid(report.snapshot.id, claim_index) from error


def build_durable_memory_evidence_packet(
    session: Session,
    report_id: int,
    claim_index: int,
) -> DurableMemoryEvidencePacket:
    """Build a bounded read-only evidence packet for one quality-report claim.

    The builder loads persisted report/snapshot/session/activity evidence only. It
    does not recompute deterministic quality checks and does not mutate the DB.

    Args:
        session: Active SQLAlchemy session.
        report_id: Persisted quality report id.
        claim_index: Zero-based interpretation claim index.

    Returns:
        Bounded durable-memory evidence packet.

    Raises:
        DurableMemoryPacketError: If the report, claim, or source refs are missing.
    """
    report = _load_report(session, report_id)
    if report is None:
        raise DurableMemoryPacketError.report_not_found(report_id)

    candidate = build_candidate_from_quality_report(report, claim_index)
    source_refs = candidate.source_ref_ids[:DURABLE_SOURCE_REF_LIMIT]
    citations = _citations_by_source_ref(report.snapshot, claim_index)
    source_evidence = tuple(
        _source_ref_evidence(session, source_ref_id, citations.get(source_ref_id, {})) for source_ref_id in source_refs
    )
    memory_session = report.snapshot.session
    return DurableMemoryEvidencePacket(
        session_id=memory_session.session_id,
        repo_name=memory_session.repo_name,
        worktree_label=memory_session.worktree_label,
        snapshot_id=report.snapshot.id,
        quality_report_id=report.id,
        candidate=candidate,
        eligibility=_eligibility_envelope(report, claim_index),
        source_evidence=source_evidence,
        omitted_source_count=len(candidate.source_ref_ids) - len(source_evidence),
    )


def _load_report(session: Session, report_id: int) -> SessionInterpretationQualityReport | None:
    return session.scalar(
        select(SessionInterpretationQualityReport)
        .where(SessionInterpretationQualityReport.id == report_id)
        .options(
            joinedload(SessionInterpretationQualityReport.snapshot).joinedload(SessionInterpretationSnapshot.session),
            joinedload(SessionInterpretationQualityReport.snapshot).joinedload(
                SessionInterpretationSnapshot.transcript
            ),
        ),
    )


def _eligibility_envelope(
    report: SessionInterpretationQualityReport,
    claim_index: int,
) -> QualityEligibilityEnvelope:
    return evaluate_claim_eligibility(report, claim_index)


def _claim_at(snapshot: SessionInterpretationSnapshot, claim_index: int) -> Mapping[str, Any]:
    claims = _claims(snapshot.interpretation_json)
    if claim_index < 0 or claim_index >= len(claims):
        raise DurableMemoryPacketError.claim_missing(snapshot.id, claim_index)
    return claims[claim_index]


def _claims(interpretation_json: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    claims = interpretation_json.get("claims")
    if not isinstance(claims, list):
        return []
    return [claim for claim in claims if isinstance(claim, Mapping)]


def _citations_by_source_ref(
    snapshot: SessionInterpretationSnapshot,
    claim_index: int,
) -> dict[str, Mapping[str, Any]]:
    citations: dict[str, Mapping[str, Any]] = {}
    if not isinstance(snapshot.citations_json, list):
        return citations
    for citation in snapshot.citations_json:
        if not isinstance(citation, Mapping):
            continue
        if citation.get("usage") != "claim" or citation.get("claim_index") != claim_index:
            continue
        source_ref_id = citation.get("source_ref_id")
        if isinstance(source_ref_id, str):
            citations[source_ref_id] = citation
    return citations


def _source_ref_evidence(
    session: Session,
    source_ref_id: str,
    citation: Mapping[str, Any],
) -> SourceRefEvidence:
    activity = _activity_unit(session, citation.get("activity_unit_id"))
    return SourceRefEvidence(
        source_ref_id=source_ref_id,
        activity_unit_id=activity.id if activity is not None else _int_value(citation.get("activity_unit_id")),
        # Citation metadata preserves interpretation-time source origin; activity rows are older-data fallback.
        source_origin=_string_value(citation.get("source_origin")) or (activity.source_origin if activity else None),
        activity_kind=activity.kind if activity is not None else _string_value(citation.get("activity_kind")),
        activity_ordinal=activity.ordinal if activity is not None else _int_value(citation.get("activity_index")),
        episode_ordinal=_int_value(citation.get("episode_ordinal")),
        activity_text=_bounded_text(activity.activity_text, DURABLE_ACTIVITY_TEXT_CHAR_LIMIT)
        if activity is not None and activity.activity_text is not None
        else None,
        citation_metadata=_bounded_json(dict(citation)),
    )


def _activity_unit(session: Session, activity_unit_id: Any) -> ActivityUnit | None:
    if not isinstance(activity_unit_id, int):
        return None
    return session.get(ActivityUnit, activity_unit_id)


def _content_hash(claim: Mapping[str, Any]) -> str:
    payload = {
        "kind": _string_value(claim.get("kind")),
        "statement": _string_value(claim.get("statement")),
        "confidence": _float_value(claim.get("confidence")),
        "source_ref_ids": _source_ref_ids(claim),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _source_ref_ids(claim: Mapping[str, Any]) -> list[str]:
    source_ref_ids = claim.get("source_ref_ids")
    if not isinstance(source_ref_ids, list):
        return []
    return [source_ref_id for source_ref_id in source_ref_ids if isinstance(source_ref_id, str) and source_ref_id]


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


def _bounded_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _bounded_json(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, tuple | list):
        return [_bounded_json(item) for item in value]
    if isinstance(value, str):
        return _metadata_string_or_omission(value, DURABLE_METADATA_STRING_LIMIT)
    if value is None or isinstance(value, bool | int | float):
        return value
    return _metadata_string_or_omission(str(value), DURABLE_METADATA_STRING_LIMIT)


def _metadata_string_or_omission(value: str, limit: int) -> str | Mapping[str, Any]:
    if len(value) <= limit:
        return value
    return {
        "omitted": True,
        "char_count": len(value),
        "byte_count": len(value.encode("utf-8")),
    }


def _string_value(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _int_value(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _float_value(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


__all__ = [
    "DURABLE_ACTIVITY_TEXT_CHAR_LIMIT",
    "DURABLE_METADATA_STRING_LIMIT",
    "DURABLE_SOURCE_REF_LIMIT",
    "BoundedText",
    "DurableMemoryEvidencePacket",
    "DurableMemoryPacketError",
    "SourceRefEvidence",
    "build_candidate_from_quality_report",
    "build_durable_memory_evidence_packet",
]
