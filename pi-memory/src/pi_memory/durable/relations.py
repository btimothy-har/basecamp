"""Deterministic relation assessment for durable memory records."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from pi_memory.db import (
    DURABLE_MEMORY_RELATION_TYPE_CONFLICTS,
    DURABLE_MEMORY_RELATION_TYPE_DUPLICATE,
    DURABLE_MEMORY_RELATION_TYPE_NOVEL,
    DURABLE_MEMORY_RELATION_TYPE_REFINES,
    DURABLE_MEMORY_RELATION_TYPE_REINFORCES,
    DURABLE_MEMORY_RELATION_TYPE_SUPERSEDES,
    DURABLE_MEMORY_STATUS_CANDIDATE,
    DURABLE_MEMORY_STATUS_PROMOTED,
    MEMORY_LAYER_LONG_TERM,
    MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY,
    MEMORY_PROJECTION_STATUS_DELETED,
    MEMORY_PROJECTION_STATUS_FAILED,
    MEMORY_PROJECTION_STATUS_INDEXED,
    MEMORY_PROJECTION_STATUS_PENDING,
    DurableMemoryItem,
    DurableMemoryRelation,
    MemoryProjectionRecord,
)
from pi_memory.durable.contracts import RelationAssessmentOutput, RelationType
from pi_memory.projection.contracts import MemoryProjection, ProjectionDocument, ProjectionHit, ProjectionMetadataValue
from pi_memory.projection.metadata import projection_metadata_from_record

_SOURCE_TABLE = "durable_memory_items"
_SAFE_ERROR_MAX_LENGTH = 500
_CLOSE_DISTANCE_THRESHOLD = 0.35
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "be",
        "do",
        "for",
        "in",
        "instead",
        "is",
        "it",
        "not",
        "of",
        "or",
        "prefer",
        "replace",
        "the",
        "to",
        "use",
        "with",
    },
)
_METADATA_SCALAR_KEYS = (
    "durable_memory_id",
    "status",
    "claim_kind",
    "statement",
    "normalized_statement",
    "session_id",
    "repo_name",
    "transcript_id",
    "snapshot_id",
    "quality_report_id",
)
_SUPERSEDES_PATTERNS = ("instead of", "replace")
_NEGATIVE_PATTERNS = ("do not", "don't", "avoid", "never")
_POSITIVE_PATTERNS = ("use", "prefer")


@dataclass(frozen=True)
class RelationAssessmentResult:
    """Persisted relation assessment result for one durable memory item."""

    memory_id: int
    assessment: RelationAssessmentOutput
    resolved_hit_count: int
    related_memory_id: int | None = None
    distance: float | None = None


@dataclass(frozen=True)
class _ResolvedHit:
    memory: DurableMemoryItem
    hit: ProjectionHit
    text: str


class DurableMemoryRelationError(Exception):
    """Base error for durable-memory relation assessment failures."""


class DurableMemoryNotFoundError(DurableMemoryRelationError):
    """Raised when the requested durable memory item is missing."""

    def __init__(self, memory_id: int) -> None:
        super().__init__(f"Durable memory item {memory_id} was not found")


class DurableMemoryProjectionError(DurableMemoryRelationError):
    """Raised when durable-memory projection fails."""

    def __init__(self, memory_id: int, message: str) -> None:
        super().__init__(f"Durable memory item {memory_id} projection failed: {message}")
        self.memory_id = memory_id
        self.safe_error = message


def project_durable_memory_record(
    session: Session,
    memory: DurableMemoryItem,
    projection: MemoryProjection,
) -> MemoryProjectionRecord:
    """Upsert one durable memory item into SQLite projection metadata and Chroma."""
    record = _upsert_projection_record(session, memory, projection.collection_name)
    session.flush()

    indexed_at = datetime.now(UTC)
    record.status = _projected_record_status(memory)
    record.embedding_model = projection.embedding_model
    record.last_error = None
    record.indexed_at = indexed_at
    document = _projection_document(record)

    try:
        projection.upsert([document])
    except Exception as error:  # noqa: BLE001 - projection implementations are external seams.
        safe_error = _safe_error(error)
        record.status = MEMORY_PROJECTION_STATUS_FAILED
        record.last_error = safe_error
        record.embedding_model = None
        record.indexed_at = None
        session.flush()
        raise DurableMemoryProjectionError(memory.id, safe_error) from error

    return record


def assess_durable_memory_relations(
    session: Session,
    memory_id: int,
    projection: MemoryProjection,
    *,
    limit: int = 8,
) -> RelationAssessmentResult:
    """Assess deterministic relations between a candidate and promoted durable memories."""
    memory = _load_memory(session, memory_id)
    if memory is None:
        raise DurableMemoryNotFoundError(memory_id)

    # Relation classification reads Chroma immediately, so first sync the bounded comparison set from SQLite.
    _project_candidate_and_promoted_memories(session, memory, projection)
    candidate_text = _memory_text(memory)
    hits = projection.query(
        candidate_text,
        filters={
            "record_type": MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY,
            "memory_layer": MEMORY_LAYER_LONG_TERM,
            "relation_visible": True,
        },
        limit=limit + 1,
    )
    resolved_hits = _resolve_hits(session, hits, memory_id)
    best_hit = resolved_hits[0] if resolved_hits else None
    assessment = _classify_relation(candidate_text, best_hit)
    result = RelationAssessmentResult(
        memory_id=memory.id,
        assessment=assessment,
        resolved_hit_count=len(resolved_hits),
        related_memory_id=assessment.related_memory_id,
        distance=best_hit.hit.distance if best_hit is not None else None,
    )

    memory.relation_summary_json = _result_json(result)
    if assessment.relation_type != DURABLE_MEMORY_RELATION_TYPE_NOVEL and best_hit is not None:
        _upsert_relation(session, memory, best_hit, assessment)
    return result


def _project_candidate_and_promoted_memories(
    session: Session,
    memory: DurableMemoryItem,
    projection: MemoryProjection,
) -> None:
    memories = list(
        session.scalars(
            select(DurableMemoryItem)
            .where(DurableMemoryItem.status == DURABLE_MEMORY_STATUS_PROMOTED)
            .options(joinedload(DurableMemoryItem.session)),
        ),
    )
    promoted_ids = {promoted.id for promoted in memories}
    if memory.id not in promoted_ids:
        memories.append(memory)
    for durable_memory in memories:
        project_durable_memory_record(session, durable_memory, projection)


def _load_memory(session: Session, memory_id: int) -> DurableMemoryItem | None:
    return session.scalar(
        select(DurableMemoryItem)
        .where(DurableMemoryItem.id == memory_id)
        .options(joinedload(DurableMemoryItem.session)),
    )


def _upsert_projection_record(
    session: Session,
    memory: DurableMemoryItem,
    collection_name: str,
) -> MemoryProjectionRecord:
    record_key = _record_key(memory.id)
    record = session.scalar(
        select(MemoryProjectionRecord).where(
            MemoryProjectionRecord.collection_name == collection_name,
            MemoryProjectionRecord.record_key == record_key,
        ),
    )
    metadata_json = _metadata_json(memory)
    fields = {
        "chroma_id": record_key,
        "record_type": MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY,
        "memory_layer": MEMORY_LAYER_LONG_TERM,
        "source_table": _SOURCE_TABLE,
        "source_id": memory.id,
        "snapshot_id": memory.snapshot_id,
        "quality_report_id": memory.quality_report_id,
        "durable_memory_id": memory.id,
        "claim_index": None,
        "content_hash": _content_hash(memory, metadata_json),
        "embedding_model": None,
        "embedding_dimension": None,
        "status": MEMORY_PROJECTION_STATUS_PENDING,
        "recall_visible": memory.status == DURABLE_MEMORY_STATUS_PROMOTED,
        "relation_visible": memory.status in {DURABLE_MEMORY_STATUS_CANDIDATE, DURABLE_MEMORY_STATUS_PROMOTED},
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


def _projected_record_status(memory: DurableMemoryItem) -> str:
    if memory.status in {DURABLE_MEMORY_STATUS_CANDIDATE, DURABLE_MEMORY_STATUS_PROMOTED}:
        return MEMORY_PROJECTION_STATUS_INDEXED
    return MEMORY_PROJECTION_STATUS_DELETED


def _metadata_json(memory: DurableMemoryItem) -> dict[str, Any]:
    normalized_statement = _normalized_statement(memory)
    memory_session = memory.session
    return {
        "durable_memory_id": memory.id,
        "status": memory.status,
        "claim_kind": memory.claim_kind,
        "statement": memory.statement,
        "normalized_statement": normalized_statement,
        "session_id": memory_session.session_id,
        "repo_name": memory_session.repo_name,
        "transcript_id": memory.transcript_id,
        "snapshot_id": memory.snapshot_id,
        "quality_report_id": memory.quality_report_id,
    }


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
    statement = metadata_json.get("normalized_statement") or metadata_json.get("statement")
    return str(statement or "")


def _scalar_projection_filters(metadata_json: Mapping[str, Any]) -> dict[str, ProjectionMetadataValue]:
    return {
        key: value
        for key in _METADATA_SCALAR_KEYS
        if isinstance((value := metadata_json.get(key)), str | int | float | bool)
    }


def _resolve_hits(session: Session, hits: list[ProjectionHit], memory_id: int) -> list[_ResolvedHit]:
    resolved: list[_ResolvedHit] = []
    for hit in hits:
        durable_memory_id = _int_metadata(hit.metadata.get("durable_memory_id"))
        if durable_memory_id is None or durable_memory_id == memory_id:
            continue
        memory = _load_memory(session, durable_memory_id)
        if memory is None:
            continue
        resolved.append(_ResolvedHit(memory=memory, hit=hit, text=_memory_text(memory)))
    return resolved


def _classify_relation(
    candidate_text: str,
    resolved_hit: _ResolvedHit | None,
) -> RelationAssessmentOutput:
    if resolved_hit is None:
        return _assessment(
            DURABLE_MEMORY_RELATION_TYPE_NOVEL,
            None,
            None,
            0.7,
            "No promoted durable memory hit resolved.",
        )

    related_text = resolved_hit.text
    related_memory_id = resolved_hit.memory.id
    similarity_score = _similarity_score(resolved_hit.hit.distance)
    candidate_normalized = _normalize_text(candidate_text)
    related_normalized = _normalize_text(related_text)

    if candidate_normalized == related_normalized:
        return _assessment(
            DURABLE_MEMORY_RELATION_TYPE_DUPLICATE,
            related_memory_id,
            similarity_score,
            1.0,
            "Normalized durable memory statements match exactly.",
        )
    if _supersedes(candidate_text, related_text):
        return _assessment(
            DURABLE_MEMORY_RELATION_TYPE_SUPERSEDES,
            related_memory_id,
            similarity_score,
            0.85,
            "Candidate explicitly replaces or uses an alternative instead of the related memory concept.",
        )
    if _conflicts(candidate_text, related_text):
        return _assessment(
            DURABLE_MEMORY_RELATION_TYPE_CONFLICTS,
            related_memory_id,
            similarity_score,
            0.85,
            "One memory discourages a term that the other memory recommends.",
        )
    if len(candidate_normalized) > len(related_normalized) and related_normalized in candidate_normalized:
        return _assessment(
            DURABLE_MEMORY_RELATION_TYPE_REFINES,
            related_memory_id,
            similarity_score,
            0.8,
            "Candidate statement contains the related statement with additional detail.",
        )
    if resolved_hit.hit.distance <= _CLOSE_DISTANCE_THRESHOLD:
        return _assessment(
            DURABLE_MEMORY_RELATION_TYPE_REINFORCES,
            related_memory_id,
            similarity_score,
            0.75,
            "Candidate is close to a resolved promoted durable memory in projection distance.",
        )
    return _assessment(
        DURABLE_MEMORY_RELATION_TYPE_NOVEL,
        None,
        None,
        0.7,
        "Resolved hits did not meet deterministic relation thresholds.",
    )


def _assessment(
    relation_type: RelationType,
    related_memory_id: int | None,
    similarity_score: float | None,
    confidence: float,
    rationale: str,
) -> RelationAssessmentOutput:
    return RelationAssessmentOutput(
        relation_type=relation_type,
        related_memory_id=related_memory_id,
        similarity_score=similarity_score,
        confidence=confidence,
        rationale=rationale,
        evidence_refs=[],
    )


def _upsert_relation(
    session: Session,
    memory: DurableMemoryItem,
    resolved_hit: _ResolvedHit,
    assessment: RelationAssessmentOutput,
) -> DurableMemoryRelation:
    relation = session.scalar(
        select(DurableMemoryRelation).where(
            DurableMemoryRelation.memory_id == memory.id,
            DurableMemoryRelation.related_memory_id == resolved_hit.memory.id,
            DurableMemoryRelation.relation_type == assessment.relation_type,
        ),
    )
    metadata_json = {
        "rationale": assessment.rationale,
        "chroma_id": resolved_hit.hit.chroma_id,
        "distance": resolved_hit.hit.distance,
        "classifier_mode": "deterministic-chroma-v1",
    }
    if relation is None:
        relation = DurableMemoryRelation(
            memory_id=memory.id,
            related_memory_id=resolved_hit.memory.id,
            relation_type=assessment.relation_type,
            similarity_score=assessment.similarity_score,
            confidence=assessment.confidence,
            metadata_json=metadata_json,
        )
        session.add(relation)
        return relation

    relation.similarity_score = assessment.similarity_score
    relation.confidence = assessment.confidence
    relation.metadata_json = metadata_json
    return relation


def _result_json(result: RelationAssessmentResult) -> dict[str, Any]:
    return {
        "memory_id": result.memory_id,
        "assessment": result.assessment.model_dump(mode="json"),
        "resolved_hit_count": result.resolved_hit_count,
        "related_memory_id": result.related_memory_id,
        "distance": result.distance,
    }


def _normalized_statement(memory: DurableMemoryItem) -> str | None:
    output = memory.evaluation_json.get("output") if isinstance(memory.evaluation_json, Mapping) else None
    if not isinstance(output, Mapping):
        return None
    normalized_statement = output.get("normalized_statement")
    return normalized_statement if isinstance(normalized_statement, str) and normalized_statement.strip() else None


def _memory_text(memory: DurableMemoryItem) -> str:
    return _normalized_statement(memory) or memory.statement


def _content_hash(memory: DurableMemoryItem, metadata_json: Mapping[str, Any]) -> str:
    payload = {
        "text": _document_text(metadata_json),
        "claim_kind": memory.claim_kind,
        "status": memory.status,
        "content_hash": memory.content_hash,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _record_key(memory_id: int) -> str:
    return f"durable_memory:{memory_id}"


def _similarity_score(distance: float) -> float:
    return max(0.0, min(1.0, 1.0 - distance))


def _normalize_text(text: str) -> str:
    # Stopwords stay here so polarity changes like "use" vs "do not use" do not collapse into duplicates.
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", text.lower()) if term not in _STOPWORDS and len(term) > 1}


def _has_overlap(left: str, right: str) -> bool:
    return bool(_terms(left) & _terms(right))


def _supersedes(candidate_text: str, related_text: str) -> bool:
    candidate = candidate_text.lower()
    if not any(pattern in candidate for pattern in _SUPERSEDES_PATTERNS):
        return False
    return _has_overlap(candidate_text, related_text)


def _conflicts(left: str, right: str) -> bool:
    left_lower = left.lower()
    right_lower = right.lower()
    left_negative = any(pattern in left_lower for pattern in _NEGATIVE_PATTERNS)
    right_negative = any(pattern in right_lower for pattern in _NEGATIVE_PATTERNS)
    left_positive = any(pattern in left_lower for pattern in _POSITIVE_PATTERNS)
    right_positive = any(pattern in right_lower for pattern in _POSITIVE_PATTERNS)
    return ((left_negative and right_positive) or (right_negative and left_positive)) and _has_overlap(left, right)


def _int_metadata(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _safe_error(error: Exception) -> str:
    message = str(error).strip() or type(error).__name__
    return message[:_SAFE_ERROR_MAX_LENGTH]


__all__ = [
    "DurableMemoryNotFoundError",
    "DurableMemoryProjectionError",
    "DurableMemoryRelationError",
    "RelationAssessmentResult",
    "assess_durable_memory_relations",
    "project_durable_memory_record",
]
