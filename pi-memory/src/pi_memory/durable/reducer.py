"""Deterministic reducer and persistence for durable-memory state transitions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from pi_memory.constants import (
    DURABLE_MEMORY_ARCHIVED_REASON_SUPERSEDED,
    DURABLE_MEMORY_RELATION_TYPE_CONFLICTS,
    DURABLE_MEMORY_RELATION_TYPE_DUPLICATE,
    DURABLE_MEMORY_RELATION_TYPE_NOVEL,
    DURABLE_MEMORY_RELATION_TYPE_REFINES,
    DURABLE_MEMORY_RELATION_TYPE_REINFORCES,
    DURABLE_MEMORY_RELATION_TYPE_STALE_SIGNAL,
    DURABLE_MEMORY_RELATION_TYPE_SUPERSEDES,
    DURABLE_MEMORY_STATUS_ARCHIVED,
    DURABLE_MEMORY_STATUS_CANDIDATE,
    DURABLE_MEMORY_STATUS_PROMOTED,
    DURABLE_MEMORY_STATUS_QUARANTINED,
    DURABLE_MEMORY_STATUS_REJECTED,
    MEMORY_PROJECTION_STATUS_DELETED,
)
from pi_memory.db.models import (
    DurableMemoryAuditEvent,
    DurableMemoryItem,
)
from pi_memory.durable.contracts import (
    DURABLE_AUDIT_DETAIL_STRING_MAX_LENGTH,
    CandidateEvaluationOutput,
    DurableMemoryAuditEventPayload,
    QualityEligibilityEnvelope,
    ReducerAction,
    ReducerDecision,
)
from pi_memory.durable.evaluator import CandidateEvaluationResult
from pi_memory.durable.relations import RelationAssessmentResult


@dataclass(frozen=True)
class ReducerContext:
    """Inputs for one deterministic durable-memory reducer decision."""

    memory: DurableMemoryItem
    eligibility: QualityEligibilityEnvelope
    evaluation: CandidateEvaluationOutput | None
    relation: RelationAssessmentResult | None


@dataclass(frozen=True)
class DeterministicDurableMemoryReducer:
    """Deterministic reducer for durable-memory candidate status transitions."""

    supported_min: float = 0.7
    vague_max: float = 0.5
    transient_max: float = 0.6
    durable_min: float = 0.5
    confidence_min: float = 0.5
    relation_confidence_min: float = 0.75
    supersedes_confidence_min: float = 0.85

    def decide(self, context: ReducerContext) -> ReducerDecision:
        """Decide the next durable-memory status without provider calls or persistence."""
        eligibility = context.eligibility
        if not eligibility.is_eligible:
            return _decision(
                "reject",
                DURABLE_MEMORY_STATUS_REJECTED,
                f"eligibility_blocked_{eligibility.block_reason}",
                "Quality eligibility blocked durable-memory promotion.",
            )

        evaluation = context.evaluation
        if evaluation is None:
            return _decision(
                "quarantine",
                DURABLE_MEMORY_STATUS_QUARANTINED,
                "missing_candidate_evaluation",
                "Candidate evaluation is required before durable-memory promotion.",
            )

        metric_decision = self._metric_decision(evaluation)
        if metric_decision is not None:
            return metric_decision

        relation_decision = self._relation_decision(context.relation)
        if relation_decision is not None:
            return relation_decision

        return _decision(
            "promote",
            DURABLE_MEMORY_STATUS_PROMOTED,
            "metrics_all_healthy",
            "Candidate metrics passed all deterministic reducer thresholds.",
        )

    def _metric_decision(self, evaluation: CandidateEvaluationOutput) -> ReducerDecision | None:
        metrics = evaluation.metrics
        if metrics.is_supported.score < self.supported_min:
            return _decision(
                "reject",
                DURABLE_MEMORY_STATUS_REJECTED,
                "metric_unsupported",
                "Candidate support score is below the promotion threshold.",
            )
        if metrics.is_vague.score > self.vague_max:
            return _decision(
                "reject",
                DURABLE_MEMORY_STATUS_REJECTED,
                "metric_too_vague",
                "Candidate vagueness score is above the rejection threshold.",
            )
        if metrics.is_transient.score > self.transient_max:
            return _decision(
                "reject",
                DURABLE_MEMORY_STATUS_REJECTED,
                "metric_transient",
                "Candidate transience score is above the rejection threshold.",
            )
        if metrics.is_durable.score < self.durable_min:
            return _decision(
                "quarantine",
                DURABLE_MEMORY_STATUS_QUARANTINED,
                "metric_low_durability",
                "Candidate durability score is below the promotion threshold.",
            )
        if metrics.confidence.score < self.confidence_min:
            return _decision(
                "quarantine",
                DURABLE_MEMORY_STATUS_QUARANTINED,
                "metric_low_confidence",
                "Candidate confidence score is below the promotion threshold.",
            )
        return None

    def _relation_decision(self, relation: RelationAssessmentResult | None) -> ReducerDecision | None:
        if relation is None:
            return None

        assessment = relation.assessment
        relation_type = assessment.relation_type
        if relation_type == DURABLE_MEMORY_RELATION_TYPE_DUPLICATE:
            return _decision(
                "reject",
                DURABLE_MEMORY_STATUS_REJECTED,
                "duplicate_memory",
                "Candidate duplicates an existing durable memory.",
            )
        if relation_type == DURABLE_MEMORY_RELATION_TYPE_CONFLICTS:
            return _decision(
                "quarantine",
                DURABLE_MEMORY_STATUS_QUARANTINED,
                "conflicting_memory",
                "Candidate conflicts with an existing durable memory.",
            )
        if relation_type == DURABLE_MEMORY_RELATION_TYPE_SUPERSEDES:
            if assessment.confidence >= self.supersedes_confidence_min:
                return _decision(
                    "promote",
                    DURABLE_MEMORY_STATUS_PROMOTED,
                    "supersedes_existing",
                    "Candidate supersedes an existing durable memory with sufficient confidence.",
                )
            return None
        if relation_type == DURABLE_MEMORY_RELATION_TYPE_REINFORCES:
            if assessment.confidence >= self.relation_confidence_min:
                return _decision(
                    "promote",
                    DURABLE_MEMORY_STATUS_PROMOTED,
                    "reinforces_existing",
                    "Candidate reinforces an existing durable memory with sufficient confidence.",
                )
            return None
        if relation_type == DURABLE_MEMORY_RELATION_TYPE_REFINES:
            if assessment.confidence >= self.relation_confidence_min:
                return _decision(
                    "promote",
                    DURABLE_MEMORY_STATUS_PROMOTED,
                    "refines_existing",
                    "Candidate refines an existing durable memory with sufficient confidence.",
                )
            return None
        if relation_type == DURABLE_MEMORY_RELATION_TYPE_STALE_SIGNAL:
            return _decision(
                "reject",
                DURABLE_MEMORY_STATUS_REJECTED,
                "stale_signal",
                "Candidate is a stale signal for durable memory.",
            )
        if relation_type == DURABLE_MEMORY_RELATION_TYPE_NOVEL:
            return _decision(
                "promote",
                DURABLE_MEMORY_STATUS_PROMOTED,
                "novel_memory_eligible",
                "Candidate is novel and passed deterministic reducer thresholds.",
            )
        return None


def persist_reducer_decision(
    session: Session,
    memory: DurableMemoryItem,
    decision: ReducerDecision,
    *,
    evaluation_result: CandidateEvaluationResult | None = None,
    relation_result: RelationAssessmentResult | None = None,
) -> list[DurableMemoryAuditEvent]:
    """Persist a reducer decision, projection visibility, and audit trail."""
    events = [_apply_primary_transition(session, memory, decision, evaluation_result, relation_result)]
    if _should_archive_superseded_memory(decision, relation_result):
        archived = _archive_related_superseded_memory(session, memory, relation_result)
        if archived is not None:
            events.append(archived)
    return events


def _apply_primary_transition(
    session: Session,
    memory: DurableMemoryItem,
    decision: ReducerDecision,
    evaluation_result: CandidateEvaluationResult | None,
    relation_result: RelationAssessmentResult | None,
) -> DurableMemoryAuditEvent:
    from_status = memory.status
    memory.status = decision.target_status
    memory.status_reason = decision.reason_code
    memory.archived_reason = (
        decision.archived_reason if decision.target_status == DURABLE_MEMORY_STATUS_ARCHIVED else None
    )
    memory.superseded_by_id = decision.superseded_by_id
    if evaluation_result is not None:
        memory.evaluation_json = evaluation_result.evaluation_json
    if relation_result is not None:
        memory.relation_summary_json = _relation_result_json(relation_result)
    _update_projection_visibility(memory)

    event = _audit_event(
        memory,
        event_type=_event_type(decision.action),
        from_status=from_status,
        to_status=decision.target_status,
        reason_code=decision.reason_code,
        details=_audit_details(decision, evaluation_result, relation_result),
    )
    session.add(event)
    return event


def _archive_related_superseded_memory(
    session: Session,
    memory: DurableMemoryItem,
    relation_result: RelationAssessmentResult | None,
) -> DurableMemoryAuditEvent | None:
    if relation_result is None:
        return None
    related_memory_id = relation_result.assessment.related_memory_id
    if related_memory_id is None or related_memory_id == memory.id:
        return None
    related = session.get(DurableMemoryItem, related_memory_id)
    if related is None or related.status != DURABLE_MEMORY_STATUS_PROMOTED:
        return None

    from_status = related.status
    related.status = DURABLE_MEMORY_STATUS_ARCHIVED
    related.archived_reason = DURABLE_MEMORY_ARCHIVED_REASON_SUPERSEDED
    related.superseded_by_id = memory.id
    related.status_reason = "superseded_by_candidate"
    _update_projection_visibility(related)

    event = _audit_event(
        related,
        event_type="archived",
        from_status=from_status,
        to_status=DURABLE_MEMORY_STATUS_ARCHIVED,
        reason_code="superseded_by_candidate",
        details={
            "decision_rationale": "Related promoted memory was superseded by the promoted candidate.",
            "superseded_by_id": memory.id,
            "candidate_memory_id": memory.id,
            "relation_type": relation_result.assessment.relation_type,
            "relation_confidence": relation_result.assessment.confidence,
            "relation_similarity": relation_result.assessment.similarity_score,
            "related_memory_id": related_memory_id,
        },
    )
    session.add(event)
    return event


def _should_archive_superseded_memory(
    decision: ReducerDecision,
    relation_result: RelationAssessmentResult | None,
) -> bool:
    if decision.action != "promote" or decision.reason_code != "supersedes_existing":
        return False
    if relation_result is None:
        return False
    return relation_result.assessment.relation_type == DURABLE_MEMORY_RELATION_TYPE_SUPERSEDES


def _update_projection_visibility(memory: DurableMemoryItem) -> None:
    recall_visible, relation_visible = _visibility(memory.status)
    should_delete = memory.status in {DURABLE_MEMORY_STATUS_REJECTED, DURABLE_MEMORY_STATUS_ARCHIVED}
    for record in memory.projection_records:
        record.recall_visible = recall_visible
        record.relation_visible = relation_visible
        if should_delete:
            record.status = MEMORY_PROJECTION_STATUS_DELETED
        record.metadata_json = _projection_metadata_json(memory, record.metadata_json)


def _projection_metadata_json(memory: DurableMemoryItem, metadata_json: Mapping[str, Any] | None) -> dict[str, Any]:
    metadata = dict(metadata_json or {})
    metadata["status"] = memory.status
    if memory.archived_reason is None:
        metadata.pop("archived_reason", None)
        metadata.pop("superseded_by_id", None)
        return metadata
    metadata["archived_reason"] = memory.archived_reason
    metadata["superseded_by_id"] = memory.superseded_by_id
    return metadata


def _visibility(status: str) -> tuple[bool, bool]:
    if status == DURABLE_MEMORY_STATUS_PROMOTED:
        return True, True
    if status == DURABLE_MEMORY_STATUS_CANDIDATE:
        return False, True
    return False, False


def _audit_event(
    memory: DurableMemoryItem,
    *,
    event_type: str,
    from_status: str | None,
    to_status: str | None,
    reason_code: str,
    details: Mapping[str, Any],
) -> DurableMemoryAuditEvent:
    # Validate and bound details before writing JSON through the ORM.
    payload = DurableMemoryAuditEventPayload(
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        reason_code=reason_code,
        details={key: _bounded_detail_value(value) for key, value in details.items()},
    )
    return DurableMemoryAuditEvent(
        memory=memory,
        job_id=memory.job_id,
        event_type=payload.event_type,
        from_status=payload.from_status,
        to_status=payload.to_status,
        reason_code=payload.reason_code,
        details_json=payload.details,
    )


def _audit_details(
    decision: ReducerDecision,
    evaluation_result: CandidateEvaluationResult | None,
    relation_result: RelationAssessmentResult | None,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "decision_action": decision.action,
        "decision_rationale": decision.rationale,
        "target_status": decision.target_status,
    }
    if decision.archived_reason is not None:
        details["archived_reason"] = decision.archived_reason
    if decision.superseded_by_id is not None:
        details["superseded_by_id"] = decision.superseded_by_id
    if evaluation_result is not None:
        metadata = evaluation_result.model_metadata
        details.update(
            {
                "prompt_version": evaluation_result.prompt_version,
                "schema_version": evaluation_result.schema_version,
                "provider": metadata.get("provider"),
                "model": metadata.get("model"),
                "mode": metadata.get("mode"),
            },
        )
    if relation_result is not None:
        assessment = relation_result.assessment
        details.update(
            {
                "relation_type": assessment.relation_type,
                "relation_confidence": assessment.confidence,
                "relation_similarity": assessment.similarity_score,
                "related_memory_id": assessment.related_memory_id,
            },
        )
    return details


def _relation_result_json(result: RelationAssessmentResult) -> dict[str, Any]:
    return {
        "memory_id": result.memory_id,
        "assessment": result.assessment.model_dump(mode="json"),
        "resolved_hit_count": result.resolved_hit_count,
        "related_memory_id": result.related_memory_id,
        "distance": result.distance,
    }


def _bounded_detail_value(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)[:DURABLE_AUDIT_DETAIL_STRING_MAX_LENGTH]


def _event_type(action: ReducerAction) -> str:
    return {
        "promote": "promoted",
        "quarantine": "quarantined",
        "reject": "rejected",
        "archive": "archived",
    }[action]


def _decision(action: str, target_status: str, reason_code: str, rationale: str) -> ReducerDecision:
    return ReducerDecision(
        action=action,
        target_status=target_status,
        reason_code=reason_code,
        rationale=rationale,
    )


__all__ = [
    "DeterministicDurableMemoryReducer",
    "ReducerContext",
    "persist_reducer_decision",
]
