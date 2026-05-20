"""Project eligible session interpretation claims into rebuildable memory records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from pi_memory.db import (
    MEMORY_LAYER_SHORT_TERM,
    MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
    MEMORY_PROJECTION_STATUS_DELETED,
    MEMORY_PROJECTION_STATUS_FAILED,
    MEMORY_PROJECTION_STATUS_INDEXED,
    MEMORY_PROJECTION_STATUS_PENDING,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
    MemoryProjectionRecord,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
)
from pi_memory.projection.contracts import MemoryProjection, ProjectionDocument, ProjectionMetadataValue
from pi_memory.projection.metadata import projection_metadata_from_record

_SOURCE_TABLE = "session_interpretation_snapshots"
_SAFE_ERROR_MAX_LENGTH = 500


@dataclass(frozen=True)
class SessionClaimProjectionResult:
    """Summary of session claim projection work."""

    report_id: int | None
    snapshot_id: int | None
    eligible: bool
    indexed_count: int
    skipped_count: int
    deleted_count: int
    failed_count: int
    reason: str | None = None


def project_session_claims(
    session: Session,
    report_id: int,
    projection: MemoryProjection,
) -> SessionClaimProjectionResult:
    """Project persisted interpretation claims for one quality report.

    SQLite remains canonical: this function idempotently upserts one
    ``MemoryProjectionRecord`` per current interpretation claim, marks stale claim
    indexes deleted, and mirrors eligible current records into the supplied
    semantic projection.

    Args:
        session: Active SQLAlchemy session participating in the caller's transaction.
        report_id: Persisted ``SessionInterpretationQualityReport`` id.
        projection: Rebuildable semantic projection seam.

    Returns:
        Structured counts and ineligibility reason, if any.
    """
    report = _load_report(session, report_id)
    if report is None:
        return SessionClaimProjectionResult(
            report_id=report_id,
            snapshot_id=None,
            eligible=False,
            indexed_count=0,
            skipped_count=0,
            deleted_count=0,
            failed_count=0,
            reason="report_not_found",
        )

    snapshot = report.snapshot
    claims = _claims(snapshot.interpretation_json)
    reason = _ineligible_reason(report)
    if reason is not None:
        deleted_count = _mark_missing_claims_deleted(
            session,
            snapshot_id=snapshot.id,
            current_indexes=frozenset(),
            collection_name=projection.collection_name,
        )
        return SessionClaimProjectionResult(
            report_id=report.id,
            snapshot_id=snapshot.id,
            eligible=False,
            indexed_count=0,
            skipped_count=len(claims),
            deleted_count=deleted_count,
            failed_count=0,
            reason=reason,
        )

    records = [
        _upsert_claim_record(session, report, index, claim, collection_name=projection.collection_name)
        for index, claim in enumerate(claims)
    ]
    deleted_count = _mark_missing_claims_deleted(
        session,
        snapshot_id=snapshot.id,
        current_indexes=frozenset(range(len(claims))),
        collection_name=projection.collection_name,
    )
    session.flush()

    indexed_at = datetime.now(UTC)
    for record in records:
        record.status = MEMORY_PROJECTION_STATUS_INDEXED
        record.embedding_model = projection.embedding_model
        record.last_error = None
        record.indexed_at = indexed_at

    documents = [_projection_document(record) for record in records]
    if not documents:
        return SessionClaimProjectionResult(
            report_id=report.id,
            snapshot_id=snapshot.id,
            eligible=True,
            indexed_count=0,
            skipped_count=0,
            deleted_count=deleted_count,
            failed_count=0,
        )

    try:
        projection.upsert(documents)
    except Exception as error:  # noqa: BLE001 - projection implementations are external seams.
        safe_error = _safe_error(error)
        for record in records:
            record.status = MEMORY_PROJECTION_STATUS_FAILED
            record.last_error = safe_error
            record.embedding_model = None
            record.indexed_at = None
        return SessionClaimProjectionResult(
            report_id=report.id,
            snapshot_id=snapshot.id,
            eligible=True,
            indexed_count=0,
            skipped_count=0,
            deleted_count=deleted_count,
            failed_count=len(records),
        )

    return SessionClaimProjectionResult(
        report_id=report.id,
        snapshot_id=snapshot.id,
        eligible=True,
        indexed_count=len(records),
        skipped_count=0,
        deleted_count=deleted_count,
        failed_count=0,
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


def _ineligible_reason(report: SessionInterpretationQualityReport) -> str | None:
    if report.snapshot.status != SESSION_INTERPRETATION_STATUS_COMPLETED:
        return "snapshot_not_completed"
    if report.promotable is not True:
        return "report_not_promotable"
    return None


def _claims(interpretation_json: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    claims = interpretation_json.get("claims")
    if not isinstance(claims, list):
        return []
    return [claim for claim in claims if isinstance(claim, Mapping)]


def _upsert_claim_record(
    session: Session,
    report: SessionInterpretationQualityReport,
    claim_index: int,
    claim: Mapping[str, Any],
    *,
    collection_name: str,
) -> MemoryProjectionRecord:
    snapshot = report.snapshot
    record_key = _record_key(snapshot.id, claim_index)
    record = session.scalar(
        select(MemoryProjectionRecord).where(
            MemoryProjectionRecord.collection_name == collection_name,
            MemoryProjectionRecord.record_key == record_key,
        ),
    )
    metadata_json = _metadata_json(report, claim_index, claim)
    content_hash = _content_hash(claim)

    fields = {
        "chroma_id": record_key,
        "record_type": MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
        "memory_layer": MEMORY_LAYER_SHORT_TERM,
        "source_table": _SOURCE_TABLE,
        "source_id": snapshot.id,
        "snapshot_id": snapshot.id,
        "quality_report_id": report.id,
        "durable_memory_id": None,
        "claim_index": claim_index,
        "content_hash": content_hash,
        "embedding_model": None,
        "embedding_dimension": None,
        "status": MEMORY_PROJECTION_STATUS_PENDING,
        "recall_visible": True,
        "relation_visible": True,
        "metadata_json": metadata_json,
        "last_error": None,
        "indexed_at": None,
    }
    if record is None:
        record = MemoryProjectionRecord(
            collection_name=collection_name,
            record_key=record_key,
            **fields,
        )
        session.add(record)
        return record

    for field_name, value in fields.items():
        setattr(record, field_name, value)
    return record


def _mark_missing_claims_deleted(
    session: Session,
    *,
    snapshot_id: int,
    current_indexes: frozenset[int],
    collection_name: str,
) -> int:
    records = session.scalars(
        select(MemoryProjectionRecord).where(
            MemoryProjectionRecord.collection_name == collection_name,
            MemoryProjectionRecord.record_type == MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
            MemoryProjectionRecord.source_table == _SOURCE_TABLE,
            MemoryProjectionRecord.source_id == snapshot_id,
            MemoryProjectionRecord.snapshot_id == snapshot_id,
        ),
    )
    deleted_count = 0
    for record in records:
        if record.claim_index in current_indexes:
            continue
        already_hidden = (
            record.status == MEMORY_PROJECTION_STATUS_DELETED
            and not record.recall_visible
            and not record.relation_visible
        )
        if not already_hidden:
            deleted_count += 1
        record.status = MEMORY_PROJECTION_STATUS_DELETED
        record.recall_visible = False
        record.relation_visible = False
    return deleted_count


def _metadata_json(
    report: SessionInterpretationQualityReport,
    claim_index: int,
    claim: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = report.snapshot
    memory_session = snapshot.session
    source_ref_ids = _source_ref_ids(claim)
    source_refs = _source_refs_for_claim(snapshot.citations_json, claim_index, source_ref_ids)
    return {
        "snapshot_id": snapshot.id,
        "quality_report_id": report.id,
        "claim_index": claim_index,
        "claim_kind": _string_value(claim.get("kind")),
        "claim_statement": _string_value(claim.get("statement")),
        "claim_confidence": _float_value(claim.get("confidence")),
        "source_ref_ids": source_ref_ids,
        "source_refs": source_refs,
        "source_ref_count": len(source_refs),
        "quality_status": report.quality_status,
        "quality_reason": report.quality_reason,
        "semantic_status": report.semantic_status,
        "deterministic_status": report.deterministic_status,
        "derivation_status": report.derivation_status,
        "promotable": report.promotable,
        "session_id": memory_session.session_id,
        "repo_name": memory_session.repo_name,
        "worktree_label": memory_session.worktree_label,
        "transcript_id": snapshot.transcript_id,
        "snapshot_status": snapshot.status,
    }


def _source_refs_for_claim(
    citations_json: Sequence[Mapping[str, Any]],
    claim_index: int,
    source_ref_ids: list[str],
) -> list[dict[str, Any]]:
    citations_by_ref = {
        citation.get("source_ref_id"): dict(citation)
        for citation in citations_json
        if citation.get("usage") == "claim" and citation.get("claim_index") == claim_index
    }
    return [citations_by_ref.get(source_ref_id, {"source_ref_id": source_ref_id}) for source_ref_id in source_ref_ids]


def _content_hash(claim: Mapping[str, Any]) -> str:
    payload = {
        "kind": _string_value(claim.get("kind")),
        "statement": _string_value(claim.get("statement")),
        "confidence": _float_value(claim.get("confidence")),
        "source_ref_ids": _source_ref_ids(claim),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _projection_document(record: MemoryProjectionRecord) -> ProjectionDocument:
    metadata_json = record.metadata_json
    metadata = projection_metadata_from_record(record)
    metadata.update(_scalar_projection_filters(metadata_json))
    return ProjectionDocument(
        chroma_id=record.chroma_id,
        text=_document_text(metadata_json),
        metadata=metadata,
    )


def _document_text(metadata_json: Mapping[str, Any]) -> str:
    source_refs = ", ".join(_source_ref_ids(metadata_json)) or "none"
    return "\n".join(
        [
            f"Claim kind: {metadata_json.get('claim_kind')}",
            f"Statement: {metadata_json.get('claim_statement')}",
            f"Confidence: {metadata_json.get('claim_confidence')}",
            f"Source refs: {source_refs}",
        ],
    )


def _scalar_projection_filters(metadata_json: Mapping[str, Any]) -> dict[str, ProjectionMetadataValue]:
    keys = (
        "quality_status",
        "semantic_status",
        "deterministic_status",
        "derivation_status",
        "promotable",
        "session_id",
        "repo_name",
        "worktree_label",
        "transcript_id",
        "claim_kind",
        "claim_confidence",
        "source_ref_count",
    )
    return {key: value for key in keys if isinstance((value := metadata_json.get(key)), str | int | float | bool)}


def _record_key(snapshot_id: int, claim_index: int) -> str:
    return f"session_claim:{snapshot_id}:{claim_index}"


def _source_ref_ids(claim: Mapping[str, Any]) -> list[str]:
    source_ref_ids = claim.get("source_ref_ids")
    if not isinstance(source_ref_ids, list):
        return []
    return [source_ref_id for source_ref_id in source_ref_ids if isinstance(source_ref_id, str)]


def _string_value(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _float_value(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _safe_error(error: Exception) -> str:
    message = str(error).strip() or type(error).__name__
    return message[:_SAFE_ERROR_MAX_LENGTH]
