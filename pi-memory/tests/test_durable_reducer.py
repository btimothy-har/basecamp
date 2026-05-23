from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pi_memory.db.constants import (
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
    MEMORY_LAYER_LONG_TERM,
    MEMORY_PROJECTION_COLLECTION_NAME,
    MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY,
    MEMORY_PROJECTION_STATUS_DELETED,
    MEMORY_PROJECTION_STATUS_INDEXED,
    SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
)
from pi_memory.db.database import Database
from pi_memory.db.models import (
    DurableMemoryAuditEvent,
    DurableMemoryItem,
    MemoryProjectionRecord,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    Transcript,
)
from pi_memory.durable import (
    CANDIDATE_EVALUATION_PROMPT_VERSION,
    CANDIDATE_EVALUATION_SCHEMA_VERSION,
    DeterministicDurableMemoryReducer,
    ReducerContext,
    persist_reducer_decision,
)
from pi_memory.durable.contracts import (
    CandidateEvaluationOutput,
    QualityEligibilityEnvelope,
    ReducerDecision,
    RelationAssessmentOutput,
)
from pi_memory.durable.evaluator import CandidateEvaluationResult
from pi_memory.durable.relations import RelationAssessmentResult
from sqlalchemy import select


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def database(tmp_path: Path) -> Database:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    try:
        database.initialize()
        yield database
    finally:
        database.close_if_open()


def eligibility(
    *,
    is_eligible: bool = True,
    block_reason: str | None = None,
    warning_codes: list[str] | None = None,
) -> QualityEligibilityEnvelope:
    return QualityEligibilityEnvelope(
        quality_report_id=2,
        snapshot_id=1,
        is_eligible=is_eligible,
        block_reason=block_reason,
        warning_codes=warning_codes or [],
        quality_status="healthy",
        semantic_status="passed",
        deterministic_status="passed",
        derivation_status="current",
        promotable=is_eligible,
        claim_count=1,
    )


def evaluation(
    *,
    is_supported: float = 0.9,
    is_vague: float = 0.1,
    is_durable: float = 0.9,
    is_transient: float = 0.1,
    confidence: float = 0.9,
) -> CandidateEvaluationOutput:
    return CandidateEvaluationOutput(
        normalized_statement="Use durable-memory reducer tests.",
        memory_type="decision",
        scope="cwd",
        metrics={
            "is_supported": metric(is_supported, "Supported by source evidence."),
            "is_vague": metric(is_vague, "Concrete enough for promotion."),
            "is_durable": metric(is_durable, "Durable beyond the current turn."),
            "is_transient": metric(is_transient, "Not tied to transient execution."),
            "is_overgeneralized": metric(0.1, "Bounded to the cited claim."),
            "scope_fit": metric(0.9, "Scope fits the source evidence."),
            "type_fit": metric(0.9, "Type fits the claim kind."),
            "confidence": metric(confidence, "Evaluator confidence is sufficient."),
        },
        overall_rationale="Candidate is suitable for deterministic reducer tests.",
    )


def metric(score: float, reason: str) -> dict[str, Any]:
    label = "pass" if score >= 0.7 else "warning"
    return {"score": score, "label": label, "reason": reason}


def memory_item() -> DurableMemoryItem:
    return DurableMemoryItem(
        status=DURABLE_MEMORY_STATUS_CANDIDATE,
        claim_index=0,
        claim_kind="decision",
        statement="Use durable-memory reducer tests.",
        confidence=0.9,
        content_hash="content-hash-0",
        evaluation_json={},
        relation_summary_json={},
        metadata_json={},
    )


def relation(
    relation_type: str,
    *,
    related_memory_id: int | None = 2,
    confidence: float = 0.9,
    similarity_score: float | None = 0.9,
) -> RelationAssessmentResult:
    assessment = RelationAssessmentOutput(
        relation_type=relation_type,
        related_memory_id=related_memory_id,
        similarity_score=similarity_score,
        confidence=confidence,
        rationale="Relation result for reducer tests.",
    )
    return RelationAssessmentResult(
        memory_id=1,
        assessment=assessment,
        resolved_hit_count=0 if relation_type == DURABLE_MEMORY_RELATION_TYPE_NOVEL else 1,
        related_memory_id=assessment.related_memory_id,
        distance=None if similarity_score is None else 1.0 - similarity_score,
    )


@pytest.mark.parametrize(
    ("context_kwargs", "expected_status", "expected_reason"),
    [
        (
            {
                "eligibility": eligibility(is_eligible=False, block_reason="report_not_promotable"),
                "evaluation": evaluation(),
            },
            DURABLE_MEMORY_STATUS_REJECTED,
            "eligibility_blocked_report_not_promotable",
        ),
        (
            {"eligibility": eligibility(), "evaluation": None},
            DURABLE_MEMORY_STATUS_QUARANTINED,
            "missing_candidate_evaluation",
        ),
        (
            {"eligibility": eligibility(), "evaluation": evaluation(is_supported=0.69)},
            DURABLE_MEMORY_STATUS_REJECTED,
            "metric_unsupported",
        ),
        (
            {"eligibility": eligibility(), "evaluation": evaluation(is_vague=0.51)},
            DURABLE_MEMORY_STATUS_REJECTED,
            "metric_too_vague",
        ),
        (
            {"eligibility": eligibility(), "evaluation": evaluation(is_transient=0.61)},
            DURABLE_MEMORY_STATUS_REJECTED,
            "metric_transient",
        ),
        (
            {"eligibility": eligibility(), "evaluation": evaluation(is_durable=0.49)},
            DURABLE_MEMORY_STATUS_QUARANTINED,
            "metric_low_durability",
        ),
        (
            {"eligibility": eligibility(), "evaluation": evaluation(confidence=0.49)},
            DURABLE_MEMORY_STATUS_QUARANTINED,
            "metric_low_confidence",
        ),
        (
            {
                "eligibility": eligibility(),
                "evaluation": evaluation(),
                "relation": relation(DURABLE_MEMORY_RELATION_TYPE_DUPLICATE),
            },
            DURABLE_MEMORY_STATUS_REJECTED,
            "duplicate_memory",
        ),
        (
            {
                "eligibility": eligibility(),
                "evaluation": evaluation(),
                "relation": relation(DURABLE_MEMORY_RELATION_TYPE_CONFLICTS),
            },
            DURABLE_MEMORY_STATUS_QUARANTINED,
            "conflicting_memory",
        ),
        (
            {
                "eligibility": eligibility(),
                "evaluation": evaluation(),
                "relation": relation(DURABLE_MEMORY_RELATION_TYPE_STALE_SIGNAL),
            },
            DURABLE_MEMORY_STATUS_REJECTED,
            "stale_signal",
        ),
        (
            {
                "eligibility": eligibility(),
                "evaluation": evaluation(),
                "relation": relation(DURABLE_MEMORY_RELATION_TYPE_SUPERSEDES, confidence=0.85),
            },
            DURABLE_MEMORY_STATUS_PROMOTED,
            "supersedes_existing",
        ),
        (
            {
                "eligibility": eligibility(),
                "evaluation": evaluation(),
                "relation": relation(DURABLE_MEMORY_RELATION_TYPE_REINFORCES, confidence=0.75),
            },
            DURABLE_MEMORY_STATUS_PROMOTED,
            "reinforces_existing",
        ),
        (
            {
                "eligibility": eligibility(),
                "evaluation": evaluation(),
                "relation": relation(DURABLE_MEMORY_RELATION_TYPE_REFINES, confidence=0.75),
            },
            DURABLE_MEMORY_STATUS_PROMOTED,
            "refines_existing",
        ),
        (
            {
                "eligibility": eligibility(),
                "evaluation": evaluation(),
                "relation": relation(
                    DURABLE_MEMORY_RELATION_TYPE_NOVEL,
                    related_memory_id=None,
                    similarity_score=None,
                ),
            },
            DURABLE_MEMORY_STATUS_PROMOTED,
            "novel_memory_eligible",
        ),
        (
            {"eligibility": eligibility(), "evaluation": evaluation()},
            DURABLE_MEMORY_STATUS_PROMOTED,
            "metrics_all_healthy",
        ),
    ],
)
def test_reducer_decisions_are_deterministic(
    context_kwargs: dict[str, Any],
    expected_status: str,
    expected_reason: str,
) -> None:
    reducer = DeterministicDurableMemoryReducer()
    kwargs = dict(context_kwargs)
    relation_result = kwargs.pop("relation", None)
    context = ReducerContext(memory=memory_item(), relation=relation_result, **kwargs)

    decision = reducer.decide(context)

    assert (
        decision.action
        == {
            DURABLE_MEMORY_STATUS_PROMOTED: "promote",
            DURABLE_MEMORY_STATUS_QUARANTINED: "quarantine",
            DURABLE_MEMORY_STATUS_REJECTED: "reject",
        }[expected_status]
    )
    assert decision.target_status == expected_status
    assert decision.reason_code == expected_reason


def test_low_confidence_relation_defers_to_healthy_metrics() -> None:
    reducer = DeterministicDurableMemoryReducer()
    context = ReducerContext(
        memory=memory_item(),
        eligibility=eligibility(),
        evaluation=evaluation(),
        relation=relation(DURABLE_MEMORY_RELATION_TYPE_SUPERSEDES, confidence=0.84),
    )

    decision = reducer.decide(context)

    assert decision.action == "promote"
    assert decision.target_status == DURABLE_MEMORY_STATUS_PROMOTED
    assert decision.reason_code == "metrics_all_healthy"


def test_promoted_transition_updates_projection_and_audit(database: Database) -> None:
    (candidate_id,) = create_memory_fixture(database, [{"statement": "Promote reducer output."}])
    decision = ReducerDecision(
        action="promote",
        target_status=DURABLE_MEMORY_STATUS_PROMOTED,
        reason_code="metrics_all_healthy",
        rationale="x" * 1_000,
    )
    evaluation_result = CandidateEvaluationResult(
        output=evaluation(),
        model_metadata={"provider": "pi-memory", "model": "deterministic", "mode": "test"},
        prompt_version=CANDIDATE_EVALUATION_PROMPT_VERSION,
        schema_version=CANDIDATE_EVALUATION_SCHEMA_VERSION,
    )

    with database.session() as session:
        memory = session.get(DurableMemoryItem, candidate_id)
        assert memory is not None
        events = persist_reducer_decision(session, memory, decision, evaluation_result=evaluation_result)
        assert len(events) == 1

    stored_memory = get_memory(database, candidate_id)
    stored_record = get_projection_record(database, candidate_id)
    stored_event = audit_events(database)[0]

    assert stored_memory.status == DURABLE_MEMORY_STATUS_PROMOTED
    assert stored_memory.status_reason == "metrics_all_healthy"
    assert stored_memory.evaluation_json["prompt_version"] == CANDIDATE_EVALUATION_PROMPT_VERSION
    assert stored_record.recall_visible is True
    assert stored_record.relation_visible is True
    assert stored_record.status == MEMORY_PROJECTION_STATUS_INDEXED
    assert stored_record.metadata_json["status"] == DURABLE_MEMORY_STATUS_PROMOTED
    assert stored_event.event_type == "promoted"
    assert stored_event.from_status == DURABLE_MEMORY_STATUS_CANDIDATE
    assert stored_event.to_status == DURABLE_MEMORY_STATUS_PROMOTED
    assert stored_event.reason_code == "metrics_all_healthy"
    assert len(stored_event.details_json["decision_rationale"]) == 400
    assert stored_event.details_json["model"] == "deterministic"


def test_quarantined_transition_hides_projection_without_deleting_record(database: Database) -> None:
    (candidate_id,) = create_memory_fixture(database, [{"statement": "Quarantine reducer output."}])
    decision = ReducerDecision(
        action="quarantine",
        target_status=DURABLE_MEMORY_STATUS_QUARANTINED,
        reason_code="metric_low_durability",
        rationale="Candidate durability needs more evidence.",
    )

    with database.session() as session:
        memory = session.get(DurableMemoryItem, candidate_id)
        assert memory is not None
        persist_reducer_decision(session, memory, decision)

    stored_memory = get_memory(database, candidate_id)
    stored_record = get_projection_record(database, candidate_id)
    stored_event = audit_events(database)[0]

    assert stored_memory.status == DURABLE_MEMORY_STATUS_QUARANTINED
    assert stored_record.recall_visible is False
    assert stored_record.relation_visible is False
    assert stored_record.status == MEMORY_PROJECTION_STATUS_INDEXED
    assert stored_record.metadata_json["status"] == DURABLE_MEMORY_STATUS_QUARANTINED
    assert stored_event.event_type == "quarantined"


def test_rejected_transition_hides_and_deletes_projection_record(database: Database) -> None:
    (candidate_id,) = create_memory_fixture(database, [{"statement": "Reject reducer output."}])
    decision = ReducerDecision(
        action="reject",
        target_status=DURABLE_MEMORY_STATUS_REJECTED,
        reason_code="metric_unsupported",
        rationale="Candidate support failed.",
    )

    with database.session() as session:
        memory = session.get(DurableMemoryItem, candidate_id)
        assert memory is not None
        persist_reducer_decision(session, memory, decision)

    stored_memory = get_memory(database, candidate_id)
    stored_record = get_projection_record(database, candidate_id)
    stored_event = audit_events(database)[0]

    assert stored_memory.status == DURABLE_MEMORY_STATUS_REJECTED
    assert stored_record.recall_visible is False
    assert stored_record.relation_visible is False
    assert stored_record.status == MEMORY_PROJECTION_STATUS_DELETED
    assert stored_record.metadata_json["status"] == DURABLE_MEMORY_STATUS_REJECTED
    assert stored_event.event_type == "rejected"


def test_supersedes_transition_archives_only_related_promoted_memory(database: Database) -> None:
    candidate_id, related_id, unrelated_id = create_memory_fixture(
        database,
        [
            {"statement": "Use SQLite instead of legacy observer storage."},
            {"status": DURABLE_MEMORY_STATUS_PROMOTED, "statement": "Use legacy observer storage."},
            {"status": DURABLE_MEMORY_STATUS_PROMOTED, "statement": "Keep unrelated memory."},
        ],
    )
    relation_result = relation(DURABLE_MEMORY_RELATION_TYPE_SUPERSEDES, related_memory_id=related_id, confidence=0.9)
    decision = ReducerDecision(
        action="promote",
        target_status=DURABLE_MEMORY_STATUS_PROMOTED,
        reason_code="supersedes_existing",
        rationale="Candidate supersedes related memory.",
    )

    evaluation_result = CandidateEvaluationResult(
        output=evaluation(),
        model_metadata={"provider": "pi-memory", "model": "deterministic", "mode": "test"},
        prompt_version=CANDIDATE_EVALUATION_PROMPT_VERSION,
        schema_version=CANDIDATE_EVALUATION_SCHEMA_VERSION,
    )

    with database.session() as session:
        candidate = session.get(DurableMemoryItem, candidate_id)
        assert candidate is not None
        events = persist_reducer_decision(
            session,
            candidate,
            decision,
            evaluation_result=evaluation_result,
            relation_result=relation_result,
        )
        assert len(events) == 2

    candidate = get_memory(database, candidate_id)
    related = get_memory(database, related_id)
    unrelated = get_memory(database, unrelated_id)
    candidate_record = get_projection_record(database, candidate_id)
    related_record = get_projection_record(database, related_id)
    unrelated_record = get_projection_record(database, unrelated_id)
    events = audit_events(database)

    assert candidate.status == DURABLE_MEMORY_STATUS_PROMOTED
    assert candidate.relation_summary_json["assessment"]["relation_type"] == DURABLE_MEMORY_RELATION_TYPE_SUPERSEDES
    assert candidate.relation_summary_json["assessment"]["related_memory_id"] == related_id
    assert related.status == DURABLE_MEMORY_STATUS_ARCHIVED
    assert related.archived_reason == DURABLE_MEMORY_ARCHIVED_REASON_SUPERSEDED
    assert related.superseded_by_id == candidate_id
    assert related.status_reason == "superseded_by_candidate"
    assert unrelated.status == DURABLE_MEMORY_STATUS_PROMOTED

    assert candidate_record.recall_visible is True
    assert candidate_record.relation_visible is True
    assert related_record.recall_visible is False
    assert related_record.relation_visible is False
    assert related_record.status == MEMORY_PROJECTION_STATUS_DELETED
    assert related_record.metadata_json["status"] == DURABLE_MEMORY_STATUS_ARCHIVED
    assert related_record.metadata_json["archived_reason"] == DURABLE_MEMORY_ARCHIVED_REASON_SUPERSEDED
    assert related_record.metadata_json["superseded_by_id"] == candidate_id
    assert unrelated_record.recall_visible is True
    assert unrelated_record.relation_visible is True
    assert unrelated_record.status == MEMORY_PROJECTION_STATUS_INDEXED

    assert [(event.memory_id, event.event_type) for event in events] == [
        (candidate_id, "promoted"),
        (related_id, "archived"),
    ]
    assert events[0].details_json["model"] == "deterministic"
    assert events[0].details_json["relation_type"] == DURABLE_MEMORY_RELATION_TYPE_SUPERSEDES
    assert events[0].details_json["related_memory_id"] == related_id
    assert events[1].reason_code == "superseded_by_candidate"
    assert events[1].details_json["candidate_memory_id"] == candidate_id


def test_supersedes_self_relation_does_not_archive_primary_candidate(database: Database) -> None:
    (candidate_id,) = create_memory_fixture(database, [{"statement": "Self relation should not archive."}])
    relation_result = relation(
        DURABLE_MEMORY_RELATION_TYPE_SUPERSEDES,
        related_memory_id=candidate_id,
        confidence=0.9,
    )
    decision = ReducerDecision(
        action="promote",
        target_status=DURABLE_MEMORY_STATUS_PROMOTED,
        reason_code="supersedes_existing",
        rationale="Malformed self relation should not archive the candidate.",
    )

    with database.session() as session:
        candidate = session.get(DurableMemoryItem, candidate_id)
        assert candidate is not None
        events = persist_reducer_decision(session, candidate, decision, relation_result=relation_result)
        assert len(events) == 1

    candidate = get_memory(database, candidate_id)
    events = audit_events(database)

    assert candidate.status == DURABLE_MEMORY_STATUS_PROMOTED
    assert candidate.archived_reason is None
    assert candidate.superseded_by_id is None
    assert [(event.memory_id, event.event_type) for event in events] == [(candidate_id, "promoted")]


def create_memory_fixture(database: Database, memories: list[dict[str, Any]]) -> list[int]:
    with database.session() as session:
        memory_session = MemorySession(
            session_id="pi-session-1",
            cwd="/repo/basecamp",
            worktree_label="wt-memory",
        )
        transcript = Transcript(session=memory_session, path="/tmp/pi/transcript.jsonl")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            transcript=transcript,
            status=SESSION_INTERPRETATION_STATUS_COMPLETED,
            analyzed_through_byte_offset=123,
            claim_source_activity_count=2,
            interpretation_json={"summary": "Session summary.", "claims": []},
            citations_json=[],
            prompt_version="interpretation-v1",
        )
        report = SessionInterpretationQualityReport(
            snapshot=snapshot,
            quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
            quality_reason=None,
            derivation_status=SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
            deterministic_status=SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
            semantic_status=SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
            promotable=True,
            claim_assessments_json=[],
            prompt_version="quality-v1",
        )
        session.add(report)
        session.flush()

        ids: list[int] = []
        for index, spec in enumerate(memories):
            memory = DurableMemoryItem(
                session=memory_session,
                transcript=transcript,
                snapshot=snapshot,
                quality_report=report,
                status=spec.get("status", DURABLE_MEMORY_STATUS_CANDIDATE),
                claim_index=index,
                claim_kind=spec.get("claim_kind", "decision"),
                statement=spec["statement"],
                confidence=0.9,
                content_hash=f"content-hash-{index}",
                evaluation_json={},
                relation_summary_json={},
                metadata_json={},
            )
            session.add(memory)
            session.flush()
            projection_record = MemoryProjectionRecord(
                collection_name=MEMORY_PROJECTION_COLLECTION_NAME,
                chroma_id=f"durable_memory:{memory.id}",
                record_key=f"durable_memory:{memory.id}",
                record_type=MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY,
                memory_layer=MEMORY_LAYER_LONG_TERM,
                source_table="durable_memory_items",
                source_id=memory.id,
                snapshot_id=snapshot.id,
                quality_report_id=report.id,
                durable_memory_id=memory.id,
                claim_index=None,
                content_hash=f"projection-hash-{memory.id}",
                embedding_model="fake-embedding-model",
                embedding_dimension=None,
                status=MEMORY_PROJECTION_STATUS_INDEXED,
                recall_visible=memory.status == DURABLE_MEMORY_STATUS_PROMOTED,
                relation_visible=memory.status in {DURABLE_MEMORY_STATUS_CANDIDATE, DURABLE_MEMORY_STATUS_PROMOTED},
                metadata_json={"status": memory.status, "statement": memory.statement},
            )
            session.add(projection_record)
            ids.append(memory.id)
        return ids


def get_memory(database: Database, memory_id: int) -> DurableMemoryItem:
    with database.session() as session:
        memory = session.get(DurableMemoryItem, memory_id)
        assert memory is not None
        session.expunge(memory)
        return memory


def get_projection_record(database: Database, memory_id: int) -> MemoryProjectionRecord:
    with database.session() as session:
        record = session.scalar(
            select(MemoryProjectionRecord).where(MemoryProjectionRecord.durable_memory_id == memory_id),
        )
        assert record is not None
        session.expunge(record)
        return record


def audit_events(database: Database) -> list[DurableMemoryAuditEvent]:
    with database.session() as session:
        events = list(session.scalars(select(DurableMemoryAuditEvent).order_by(DurableMemoryAuditEvent.id)))
        for event in events:
            session.expunge(event)
        return events
