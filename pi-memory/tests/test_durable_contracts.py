from __future__ import annotations

import pytest
from pi_memory.durable import (
    CandidateEvaluationMetrics,
    CandidateEvaluationOutput,
    CandidateMetricScore,
    DurableMemoryAuditEventPayload,
    DurableMemoryCandidate,
    QualityEligibilityEnvelope,
    ReducerDecision,
    RelationAssessmentOutput,
)
from pydantic import ValidationError


def metric(label: str = "pass") -> CandidateMetricScore:
    return CandidateMetricScore(score=0.9, label=label, reason="Supported by cited evidence.")


def metrics() -> CandidateEvaluationMetrics:
    return CandidateEvaluationMetrics(
        is_supported=metric(),
        is_vague=metric("warning"),
        is_durable=metric(),
        is_transient=metric(),
        is_overgeneralized=metric(),
        scope_fit=metric(),
        type_fit=metric(),
        confidence=metric(),
    )


def test_durable_memory_candidate_rejects_invalid_shape() -> None:
    DurableMemoryCandidate(
        snapshot_id=1,
        quality_report_id=2,
        claim_index=0,
        claim_kind="decision",
        statement="Remember source-backed durable facts.",
        confidence=0.8,
        source_ref_ids=["source-1"],
        content_hash="hash",
    )

    with pytest.raises(ValidationError):
        DurableMemoryCandidate(
            snapshot_id=1,
            quality_report_id=2,
            claim_index=-1,
            claim_kind="decision",
            statement="Remember source-backed durable facts.",
            confidence=0.8,
            source_ref_ids=["source-1"],
            content_hash="hash",
        )
    with pytest.raises(ValidationError):
        DurableMemoryCandidate(
            snapshot_id=1,
            quality_report_id=2,
            claim_index=0,
            claim_kind="decision",
            statement="Remember source-backed durable facts.",
            confidence=1.1,
            source_ref_ids=["source-1"],
            content_hash="hash",
        )
    with pytest.raises(ValidationError):
        DurableMemoryCandidate(
            snapshot_id=1,
            quality_report_id=2,
            claim_index=0,
            claim_kind="decision",
            statement="Remember source-backed durable facts.",
            confidence=0.8,
            source_ref_ids=[],
            content_hash="hash",
        )


def test_candidate_evaluation_output_accepts_valid_shape() -> None:
    output = CandidateEvaluationOutput(
        normalized_statement="Use durable memory contracts for later reducers.",
        memory_type="decision",
        scope="repo",
        metrics=metrics(),
        overall_rationale="The claim is source-backed and durable.",
    )

    assert output.memory_type == "decision"
    assert output.metrics.scope_fit.label == "pass"


def test_contracts_reject_extra_fields_bad_enums_and_bounds() -> None:
    with pytest.raises(ValidationError):
        CandidateMetricScore(score=0.5, label="pass", reason="ok", raw_text="secret")
    with pytest.raises(ValidationError):
        CandidateMetricScore(score=1.2, label="pass", reason="out of range")
    with pytest.raises(ValidationError):
        CandidateEvaluationOutput(
            normalized_statement="A statement.",
            memory_type="observation",
            scope="repo",
            metrics=metrics(),
        )
    with pytest.raises(ValidationError):
        CandidateEvaluationOutput(
            normalized_statement="A statement.",
            memory_type="decision",
            scope="workspace",
            metrics=metrics(),
        )


def test_quality_eligibility_envelope_requires_consistent_block_reason() -> None:
    with pytest.raises(ValidationError):
        QualityEligibilityEnvelope(
            quality_report_id=1,
            snapshot_id=2,
            is_eligible=False,
            quality_status="healthy",
            semantic_status="passed",
            deterministic_status="passed",
            derivation_status="current",
            promotable=True,
            claim_count=1,
        )
    with pytest.raises(ValidationError):
        QualityEligibilityEnvelope(
            quality_report_id=1,
            snapshot_id=2,
            is_eligible=True,
            block_reason="report_not_promotable",
            quality_status="healthy",
            semantic_status="passed",
            deterministic_status="passed",
            derivation_status="current",
            promotable=True,
            claim_count=1,
        )


def test_relation_assessment_requires_related_memory_for_non_novel_only() -> None:
    RelationAssessmentOutput(
        relation_type="novel",
        confidence=0.8,
        rationale="No related memory was retrieved.",
        evidence_refs=["source-1"],
    )

    with pytest.raises(ValidationError):
        RelationAssessmentOutput(
            relation_type="novel",
            related_memory_id=10,
            confidence=0.8,
            rationale="Novel cannot point to an existing memory.",
        )
    with pytest.raises(ValidationError):
        RelationAssessmentOutput(
            relation_type="duplicate",
            confidence=0.8,
            rationale="Duplicate requires a target memory.",
        )


def test_reducer_decision_enforces_archival_invariants() -> None:
    ReducerDecision(
        action="archive",
        target_status="archived",
        reason_code="superseded",
        rationale="A newer memory supersedes this one.",
        archived_reason="superseded",
        superseded_by_id=42,
    )

    with pytest.raises(ValidationError):
        ReducerDecision(
            action="archive",
            target_status="promoted",
            reason_code="stale",
            rationale="Archive must target archived status.",
            archived_reason="stale",
        )
    with pytest.raises(ValidationError):
        ReducerDecision(
            action="archive",
            target_status="archived",
            reason_code="stale",
            rationale="Archive decisions need an archived reason.",
        )
    with pytest.raises(ValidationError):
        ReducerDecision(
            action="archive",
            target_status="archived",
            reason_code="superseded",
            rationale="Superseded archives need a replacement id.",
            archived_reason="superseded",
        )
    with pytest.raises(ValidationError):
        ReducerDecision(
            action="archive",
            target_status="archived",
            reason_code="stale",
            rationale="Only superseded archives can carry a replacement id.",
            archived_reason="stale",
            superseded_by_id=42,
        )
    with pytest.raises(ValidationError):
        ReducerDecision(
            action="reject",
            target_status="rejected",
            reason_code="unsupported",
            rationale="Rejected memories cannot carry archival fields.",
            archived_reason="stale",
        )


def test_audit_payload_rejects_extra_fields_and_unbounded_details() -> None:
    DurableMemoryAuditEventPayload(
        event_type="candidate_created",
        to_status="candidate",
        details={"claim_index": 0, "source_ref": "source-1"},
    )

    with pytest.raises(ValidationError):
        DurableMemoryAuditEventPayload(event_type="created", details={})
    with pytest.raises(ValidationError):
        DurableMemoryAuditEventPayload(event_type="candidate_created", details={"raw": "x" * 401})
    with pytest.raises(ValidationError):
        DurableMemoryAuditEventPayload(event_type="candidate_created", details={}, raw_payload={})
