from __future__ import annotations

import pytest
from pi_memory.db import (
    SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_PENDING,
    SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
    SESSION_INTERPRETATION_QUALITY_STATUS_FAILED,
    SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
    SESSION_INTERPRETATION_QUALITY_STATUS_NOT_ASSESSED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_FAILED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
)
from pi_memory.quality import (
    FINDING_CODE_SUMMARY_EMPTY,
    QualityClaimAssessment,
    QualityFinding,
    QualityFindingReference,
    QualityReportDraft,
    SemanticQualityAssessmentOutput,
    compute_promotable,
)
from pydantic import ValidationError


def finding() -> QualityFinding:
    return QualityFinding(
        code=FINDING_CODE_SUMMARY_EMPTY,
        severity="critical",
        message="Summary is empty.",
        references=[QualityFindingReference(kind="snapshot", id="1")],
        details={"snapshot_id": 1},
    )


def test_quality_finding_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        QualityFinding(
            code=FINDING_CODE_SUMMARY_EMPTY,
            severity="critical",
            message="Summary is empty.",
            raw_text="do not persist raw text",
        )


def test_quality_contracts_bound_strings_and_lists() -> None:
    with pytest.raises(ValidationError):
        QualityFinding(code=FINDING_CODE_SUMMARY_EMPTY, severity="critical", message="x" * 501)
    with pytest.raises(ValidationError):
        QualityFinding(
            code=FINDING_CODE_SUMMARY_EMPTY,
            severity="critical",
            message="Summary is empty.",
            references=[QualityFindingReference(kind="snapshot", id=str(index)) for index in range(21)],
        )
    with pytest.raises(ValidationError):
        QualityFinding(
            code=FINDING_CODE_SUMMARY_EMPTY,
            severity="critical",
            message="Summary is empty.",
            details={"oversized": "x" * 301},
        )


@pytest.mark.parametrize(
    "field_values",
    [
        {"quality_status": "unknown"},
        {"quality_reason": "unknown"},
        {"derivation_status": "stale"},
        {"deterministic_status": "partial"},
        {"semantic_status": "unknown"},
    ],
)
def test_quality_report_draft_rejects_invalid_statuses(field_values: dict[str, str]) -> None:
    payload = {
        "quality_status": SESSION_INTERPRETATION_QUALITY_STATUS_NOT_ASSESSED,
        "quality_reason": SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_PENDING,
        **field_values,
    }

    with pytest.raises(ValidationError):
        QualityReportDraft(**payload)


def test_quality_report_draft_requires_reason_for_non_healthy_status() -> None:
    with pytest.raises(ValidationError):
        QualityReportDraft(quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_NOT_ASSESSED, quality_reason=None)


def test_quality_report_draft_rejects_reason_for_healthy_status() -> None:
    with pytest.raises(ValidationError):
        QualityReportDraft(
            quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
            quality_reason=SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_PENDING,
        )


def test_semantic_quality_assessment_output_accepts_valid_shape() -> None:
    output = SemanticQualityAssessmentOutput(
        semantic_status="degraded",
        findings=[finding()],
        claim_assessments=[
            QualityClaimAssessment(
                claim_index=0,
                status="weakly_supported",
                finding_codes=[FINDING_CODE_SUMMARY_EMPTY],
                source_ref_ids=["source-1"],
                rationale="Citation is too weak.",
            ),
        ],
        missing_high_signal_items=[
            {
                "kind": "decision",
                "description": "A high-signal decision was not captured.",
                "source_ref_ids": ["source-2"],
            },
        ],
    )

    assert output.semantic_status == "degraded"
    assert output.findings[0].code == FINDING_CODE_SUMMARY_EMPTY
    assert output.claim_assessments[0].claim_index == 0
    assert output.missing_high_signal_items[0].source_ref_ids == ["source-2"]


def test_quality_report_draft_json_helpers_are_plain_payloads() -> None:
    draft = QualityReportDraft(
        quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_NOT_ASSESSED,
        quality_reason=SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_PENDING,
        deterministic_findings=[finding()],
        semantic_findings=[finding()],
        claim_assessments=[QualityClaimAssessment(claim_index=0, status="supported")],
        model_metadata={"provider": "pi-memory"},
        assessment_metadata={"version": 1},
    )

    assert draft.deterministic_findings_json[0]["code"] == FINDING_CODE_SUMMARY_EMPTY
    assert draft.semantic_findings_json[0]["severity"] == "critical"
    assert draft.claim_assessments_json == [
        {"claim_index": 0, "status": "supported", "finding_codes": [], "source_ref_ids": [], "rationale": None},
    ]
    assert draft.missing_high_signal_items_json == []
    assert draft.model_metadata_json == {"provider": "pi-memory"}
    assert draft.assessment_metadata_json == {"version": 1}


def test_compute_promotable_matrix() -> None:
    base = {
        "snapshot_status": SESSION_INTERPRETATION_STATUS_COMPLETED,
        "derivation_status": SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
        "deterministic_status": SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
        "semantic_status": SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
        "quality_status": SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
    }

    assert compute_promotable(**base) is True
    assert (
        compute_promotable(
            **{
                **base,
                "semantic_status": SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED,
                "quality_status": SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
            }
        )
        is True
    )
    assert (
        compute_promotable(
            **{
                **base,
                "semantic_status": SESSION_INTERPRETATION_SEMANTIC_STATUS_FAILED,
                "quality_status": SESSION_INTERPRETATION_QUALITY_STATUS_FAILED,
            }
        )
        is False
    )
    assert compute_promotable(**{**base, "snapshot_status": "blocked"}) is False
    assert compute_promotable(**{**base, "derivation_status": "outdated"}) is False
    assert compute_promotable(**{**base, "deterministic_status": "failed"}) is False
    assert (
        compute_promotable(**{**base, "semantic_status": SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED}) is False
    )
    assert compute_promotable(**{**base, "quality_status": SESSION_INTERPRETATION_QUALITY_STATUS_NOT_ASSESSED}) is False
