"""Durable memory promotion helpers for pipeline jobs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pi_memory.db import (
    DURABLE_MEMORY_SOURCE_KIND_CLAIM,
    DURABLE_MEMORY_STATUS_ARCHIVED,
    DURABLE_MEMORY_STATUS_CANDIDATE,
    DURABLE_MEMORY_STATUS_PROMOTED,
    DURABLE_MEMORY_STATUS_QUARANTINED,
    DURABLE_MEMORY_STATUS_REJECTED,
    SOURCE_ORIGIN_UNKNOWN,
    SOURCE_ORIGINS,
    DurableMemoryAuditEvent,
    DurableMemoryItem,
    DurableMemorySource,
    SessionInterpretationQualityReport,
)
from pi_memory.durable import DurableMemoryEvidencePacket, project_durable_memory_record
from pi_memory.durable.relations import RelationAssessmentResult
from pi_memory.projection.contracts import MemoryProjection

PROMOTION_TERMINAL_STATUSES = {
    DURABLE_MEMORY_STATUS_ARCHIVED,
    DURABLE_MEMORY_STATUS_PROMOTED,
    DURABLE_MEMORY_STATUS_QUARANTINED,
    DURABLE_MEMORY_STATUS_REJECTED,
}

type CandidateUpsertOutcome = Literal["created", "updated", "skipped"]


def upsert_durable_memory_candidate(
    session: Session,
    packet: DurableMemoryEvidencePacket,
    job_id: int,
) -> tuple[DurableMemoryItem, CandidateUpsertOutcome]:
    candidate = packet.candidate
    report = session.get_one(SessionInterpretationQualityReport, candidate.quality_report_id)
    memory = session.scalar(
        select(DurableMemoryItem).where(
            DurableMemoryItem.quality_report_id == candidate.quality_report_id,
            DurableMemoryItem.claim_index == candidate.claim_index,
        ),
    )
    outcome: CandidateUpsertOutcome = "updated"
    if memory is None:
        outcome = "created"
        memory = DurableMemoryItem(
            session_id=report.snapshot.session_id,
            transcript_id=report.snapshot.transcript_id,
            snapshot_id=candidate.snapshot_id,
            quality_report_id=candidate.quality_report_id,
            claim_index=candidate.claim_index,
            status=DURABLE_MEMORY_STATUS_CANDIDATE,
            claim_kind=candidate.claim_kind,
            statement=candidate.statement,
            confidence=candidate.confidence,
            content_hash=candidate.content_hash,
        )
        session.add(memory)
    elif memory.status in PROMOTION_TERMINAL_STATUSES and memory.content_hash == candidate.content_hash:
        return memory, "skipped"

    memory.session_id = report.snapshot.session_id
    memory.transcript_id = report.snapshot.transcript_id
    memory.snapshot_id = candidate.snapshot_id
    memory.quality_report_id = candidate.quality_report_id
    memory.job_id = job_id
    memory.status = DURABLE_MEMORY_STATUS_CANDIDATE
    memory.status_reason = None
    memory.archived_reason = None
    memory.superseded_by_id = None
    memory.claim_kind = candidate.claim_kind
    memory.statement = candidate.statement
    memory.confidence = candidate.confidence
    memory.content_hash = candidate.content_hash
    memory.metadata_json = {
        **dict(memory.metadata_json or {}),
        "source_ref_ids": list(candidate.source_ref_ids),
        "omitted_source_count": packet.omitted_source_count,
    }
    session.flush()
    session.refresh(memory)
    return memory, outcome


def replace_durable_memory_sources(
    session: Session,
    memory: DurableMemoryItem,
    packet: DurableMemoryEvidencePacket,
) -> None:
    session.execute(delete(DurableMemorySource).where(DurableMemorySource.memory_id == memory.id))
    for evidence in packet.source_evidence:
        source_origin = evidence.source_origin if evidence.source_origin in SOURCE_ORIGINS else SOURCE_ORIGIN_UNKNOWN
        session.add(
            DurableMemorySource(
                memory_id=memory.id,
                snapshot_id=packet.snapshot_id,
                quality_report_id=packet.quality_report_id,
                activity_unit_id=evidence.activity_unit_id,
                claim_index=packet.candidate.claim_index,
                source_ref=evidence.source_ref_id,
                source_origin=source_origin,
                source_kind=DURABLE_MEMORY_SOURCE_KIND_CLAIM,
                metadata_json=_source_metadata_json(evidence),
            ),
        )
    session.flush()


def _source_metadata_json(evidence: Any) -> dict[str, Any]:
    return {
        "activity_kind": evidence.activity_kind,
        "activity_ordinal": evidence.activity_ordinal,
        "episode_ordinal": evidence.episode_ordinal,
        "citation_metadata": dict(evidence.citation_metadata),
    }


def add_durable_memory_audit_event(
    session: Session,
    memory: DurableMemoryItem,
    *,
    event_type: str,
    from_status: str | None,
    to_status: str | None,
    reason_code: str,
    details: Mapping[str, Any],
) -> DurableMemoryAuditEvent:
    event = DurableMemoryAuditEvent(
        memory=memory,
        job_id=memory.job_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        reason_code=reason_code,
        details_json={key: _audit_detail_value(value) for key, value in details.items()},
    )
    session.add(event)
    return event


def add_relation_assessed_audit_event(
    session: Session,
    memory: DurableMemoryItem,
    result: RelationAssessmentResult,
) -> None:
    add_durable_memory_audit_event(
        session,
        memory,
        event_type="relation_assessed",
        from_status=memory.status,
        to_status=memory.status,
        reason_code=result.assessment.relation_type,
        details={
            "relation_type": result.assessment.relation_type,
            "related_memory_id": result.related_memory_id,
            "resolved_hit_count": result.resolved_hit_count,
            "distance": result.distance,
        },
    )


def project_archived_related_memory(
    session: Session,
    memory: DurableMemoryItem,
    relation_result: RelationAssessmentResult,
    projection: MemoryProjection,
) -> None:
    related_memory_id = relation_result.related_memory_id
    if related_memory_id is None or related_memory_id == memory.id:
        return
    related = session.get(DurableMemoryItem, related_memory_id)
    if related is not None and related.status == DURABLE_MEMORY_STATUS_ARCHIVED:
        project_durable_memory_record(session, related, projection)


def _audit_detail_value(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)[:400]
