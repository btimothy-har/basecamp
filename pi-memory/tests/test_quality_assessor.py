from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import pytest
from pi_memory.interpretation import BoundedText
from pi_memory.quality import (
    DETERMINISTIC_QUALITY_ASSESSOR_MODE,
    FINDING_CODE_QUALITY_ASSESSMENT_REFERENCE_UNRESOLVED,
    PYDANTIC_AI_QUALITY_ASSESSOR_MODE,
    QUALITY_ASSESSMENT_PROMPT_VERSION,
    QUALITY_BOUNDED_TEXT_MAX_LENGTH,
    QUALITY_CLAIM_ASSESSMENTS_MAX_LENGTH,
    QUALITY_MISSING_HIGH_SIGNAL_ITEMS_MAX_LENGTH,
    QUALITY_SEMANTIC_FINDINGS_MAX_LENGTH,
    QUALITY_STATUS_DEGRADED,
    QUALITY_STATUS_HEALTHY,
    QUALITY_STATUS_NOT_ASSESSED,
    QUALITY_STATUS_REASON_SEMANTIC_ASSESSMENT_PENDING,
    QUALITY_STATUS_REASON_SEMANTIC_DEGRADED,
    SEMANTIC_STATUS_DEGRADED,
    SEMANTIC_STATUS_NOT_ASSESSED,
    SEMANTIC_STATUS_PASSED,
    DeterministicQualityAssessor,
    PydanticAIQualityAssessmentError,
    PydanticAIQualityAssessor,
    QualityActivityContext,
    QualityAssessmentUnavailableError,
    QualityAssessmentValidationError,
    QualityPacket,
    QualityPacketReadiness,
    QualityReportDraft,
    SemanticQualityAssessmentOutput,
    validate_quality_assessment_output,
    validate_quality_assessment_result,
)


class ProviderBodyShouldBeHiddenError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("provider body should be hidden")


class RunResult:
    def __init__(self, output: Any) -> None:
        self.output = output


def report() -> QualityReportDraft:
    return QualityReportDraft(
        quality_status=QUALITY_STATUS_NOT_ASSESSED,
        quality_reason=QUALITY_STATUS_REASON_SEMANTIC_ASSESSMENT_PENDING,
        deterministic_status="passed",
        semantic_status=SEMANTIC_STATUS_NOT_ASSESSED,
    )


def packet(
    *,
    can_assess: bool = True,
    snapshot_metadata: dict[str, Any] | None = None,
) -> QualityPacket:
    deterministic_report = report()
    return QualityPacket(
        snapshot_id=1,
        session_metadata={"session_row_id": 1, "stable_session_id": "pi-session-1"},
        snapshot_metadata=snapshot_metadata or {"snapshot_id": 1, "analysis_run_id": 2},
        readiness=QualityPacketReadiness(
            snapshot_id=1,
            snapshot_status="completed",
            derivation_status="current",
            deterministic_status="passed",
            quality_status=deterministic_report.quality_status,
            quality_reason=deterministic_report.quality_reason,
            semantic_status=deterministic_report.semantic_status,
            can_assess_semantically=can_assess,
            blocked_reason=None,
            deterministic_findings=(),
        ),
        interpretation={
            "summary": "The session chose quality reports.",
            "claims": [
                {
                    "source_ref_ids": ["source-1"],
                    "kind": "decision",
                    "statement": "Add quality reports.",
                    "confidence": 0.9,
                },
            ],
        },
        citations=({"source_ref_id": "source-1", "activity_unit_id": 10},),
        activities=(
            QualityActivityContext(
                activity_unit_id=10,
                ordinal=0,
                kind="user_text",
                source_origin="local",
                activity_text_kind="deterministic",
                activity_text_status="completed",
                byte_start=0,
                byte_end=10,
                source_ref_ids=("source-1",),
                activity_text=BoundedText(
                    text="Choose quality reports.",
                    original_char_count=23,
                    original_byte_count=23,
                    is_truncated=False,
                    omitted_char_count=0,
                    omitted_byte_count=0,
                ),
            ),
        ),
        omitted_activity_count=0,
        deterministic_report=deterministic_report,
    )


def semantic_output(status: str = SEMANTIC_STATUS_PASSED) -> dict[str, Any]:
    return {
        "semantic_status": status,
        "findings": [],
        "claim_assessments": [
            {
                "claim_index": 0,
                "status": "supported",
                "source_ref_ids": ["source-1"],
            },
        ],
        "missing_high_signal_items": [],
        "overall_rationale": "The interpretation is supported.",
    }


def alias_semantic_output() -> dict[str, Any]:
    return {
        "semantic_status": SEMANTIC_STATUS_PASSED,
        "findings": [
            {
                "code": "weak_source_support",
                "severity": "warning",
                "message": "Source s0001 needs review.",
                "references": [{"kind": "source_ref", "id": "s0001"}],
                "details": {"source_ref": "s0001"},
            },
        ],
        "claim_assessments": [
            {
                "claim_index": 0,
                "status": "supported",
                "source_ref_ids": ["s0001"],
                "rationale": "s0001 supports the claim.",
            },
        ],
        "missing_high_signal_items": [
            {
                "kind": "decision",
                "description": "A decision near s0001 was missed.",
                "source_ref_ids": ["s0001"],
            },
        ],
        "overall_rationale": "s0001 supports the interpretation.",
    }


def recoverable_reference_defect_output() -> dict[str, Any]:
    return {
        "semantic_status": SEMANTIC_STATUS_PASSED,
        "findings": [
            {
                "code": "weak_source_support",
                "severity": "warning",
                "message": "A quality finding has mixed references.",
                "references": [
                    {"kind": "source_ref", "id": "source-1"},
                    {"kind": "source_ref", "id": "activity_unit_id:111"},
                    {"kind": "claim", "id": "0"},
                ],
            },
        ],
        "claim_assessments": [
            {
                "claim_index": 0,
                "status": "supported",
                "source_ref_ids": ["source-1", "1"],
                "rationale": "The claim remains supported by the known source.",
            },
        ],
        "missing_high_signal_items": [
            {
                "kind": "decision",
                "description": "A missed decision has an invalid assessor source pointer.",
                "source_ref_ids": ["activity_unit_id:111"],
            },
        ],
        "overall_rationale": "The interpretation is mostly supported.",
    }


def test_pydantic_ai_quality_assessor_returns_report_and_safe_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "SECRET_PROVIDER_KEY_SHOULD_NOT_LEAK")

    class FakeAgent:
        def __init__(self, model: str, *, output_type: type) -> None:
            self.model = model
            self.output_type = output_type

        def run_sync(self, prompt: str) -> RunResult:
            prompts.append(prompt)
            return RunResult(semantic_output())

    assessor = PydanticAIQualityAssessor("anthropic:claude-haiku-4-5", agent_factory=FakeAgent)
    draft = assessor.assess(packet())

    assert draft.quality_status == QUALITY_STATUS_HEALTHY
    assert draft.quality_reason is None
    assert draft.semantic_status == SEMANTIC_STATUS_PASSED
    assert draft.promotable is True
    assert draft.prompt_version == QUALITY_ASSESSMENT_PROMPT_VERSION
    assert draft.model_metadata == {
        "provider": "anthropic",
        "model": "anthropic:claude-haiku-4-5",
        "mode": PYDANTIC_AI_QUALITY_ASSESSOR_MODE,
        "schema_version": 1,
    }
    assert "Quality packet JSON" in prompts[0]
    assert "short source-ref aliases" in prompts[0]
    assert '"source_ref_id":"s0001"' in prompts[0]
    assert '"source_ref_ids":["s0001"]' in prompts[0]
    assert "source-1" not in prompts[0]
    assert f"<= {QUALITY_BOUNDED_TEXT_MAX_LENGTH} characters" in prompts[0]
    assert f"findings must contain <= {QUALITY_SEMANTIC_FINDINGS_MAX_LENGTH} items" in prompts[0]
    assert f"claim_assessments must contain <= {QUALITY_CLAIM_ASSESSMENTS_MAX_LENGTH} items" in prompts[0]
    assert (
        f"missing_high_signal_items must contain <= {QUALITY_MISSING_HIGH_SIGNAL_ITEMS_MAX_LENGTH} items" in prompts[0]
    )
    assert "overall_rationale may be null" in prompts[0]
    assert "raw_line" not in prompts[0]
    assert os.environ["ANTHROPIC_API_KEY"] not in prompts[0]


def test_pydantic_ai_quality_assessor_persists_canonical_refs_from_alias_output() -> None:
    class FakeAgent:
        def __init__(self, _model: str, *, output_type: type) -> None:
            self.output_type = output_type

        def run_sync(self, _prompt: str) -> RunResult:
            return RunResult(alias_semantic_output())

    assessor = PydanticAIQualityAssessor("anthropic:claude-haiku-4-5", agent_factory=FakeAgent)
    draft = assessor.assess(packet())

    assert draft.claim_assessments[0].source_ref_ids == ["source-1"]
    assert draft.claim_assessments[0].rationale == "source-1 supports the claim."
    assert draft.missing_high_signal_items[0].source_ref_ids == ["source-1"]
    assert draft.missing_high_signal_items[0].description == "A decision near source-1 was missed."
    assert draft.semantic_findings[0].references[0].id == "source-1"
    assert draft.semantic_findings[0].message == "Source source-1 needs review."
    assert draft.semantic_findings[0].details["source_ref"] == "source-1"
    assert "s0001" not in json.dumps(
        {
            "semantic_findings": draft.semantic_findings_json,
            "claim_assessments": draft.claim_assessments_json,
            "missing_high_signal_items": draft.missing_high_signal_items_json,
        },
    )


def test_pydantic_ai_quality_assessor_degrades_and_promotes_recoverable_reference_defects() -> None:
    class FakeAgent:
        def __init__(self, _model: str, *, output_type: type) -> None:
            self.output_type = output_type

        def run_sync(self, _prompt: str) -> RunResult:
            return RunResult(recoverable_reference_defect_output())

    assessor = PydanticAIQualityAssessor("anthropic:claude-haiku-4-5", agent_factory=FakeAgent)
    draft = assessor.assess(packet())

    assert draft.quality_status == QUALITY_STATUS_DEGRADED
    assert draft.quality_reason == QUALITY_STATUS_REASON_SEMANTIC_DEGRADED
    assert draft.semantic_status == SEMANTIC_STATUS_DEGRADED
    assert draft.promotable is True
    assert draft.claim_assessments[0].source_ref_ids == ["source-1"]
    assert draft.missing_high_signal_items[0].source_ref_ids == []
    assert draft.assessment_metadata["quality_reference_defect_count"] == 3
    finding = draft.semantic_findings[-1]
    assert finding.code == FINDING_CODE_QUALITY_ASSESSMENT_REFERENCE_UNRESOLVED
    assert finding.severity == "warning"
    assert finding.references[0].kind == "snapshot"
    persisted_payload = json.dumps(
        {
            "semantic_findings": draft.semantic_findings_json,
            "claim_assessments": draft.claim_assessments_json,
            "missing_high_signal_items": draft.missing_high_signal_items_json,
        },
    )
    assert "activity_unit_id:111" not in persisted_payload


def test_pydantic_ai_quality_assessor_supports_async_agents() -> None:
    class FakeAsyncAgent:
        def __init__(self, _model: str, *, output_type: type) -> None:
            self.output_type = output_type

        async def run(self, _prompt: str) -> RunResult:
            return RunResult(semantic_output("degraded"))

    assessor = PydanticAIQualityAssessor("openai:gpt-fast", agent_factory=FakeAsyncAgent)
    draft = asyncio.run(assessor.assess_async(packet()))

    assert draft.quality_status == QUALITY_STATUS_DEGRADED
    assert draft.quality_reason == QUALITY_STATUS_REASON_SEMANTIC_DEGRADED
    assert draft.promotable is True


def test_deterministic_quality_assessor_returns_healthy_report() -> None:
    draft = DeterministicQualityAssessor().assess(packet())

    assert draft.quality_status == QUALITY_STATUS_HEALTHY
    assert draft.model_metadata["mode"] == DETERMINISTIC_QUALITY_ASSESSOR_MODE
    assert draft.promotable is True


def test_quality_assessor_degrades_passed_semantics_for_partial_episode_coverage() -> None:
    draft = DeterministicQualityAssessor().assess(
        packet(
            snapshot_metadata={
                "snapshot_id": 1,
                "analysis_run_id": 2,
                "episode_interpretation": {"coverage_status": "partial", "failed_episode_count": 1},
            },
        ),
    )

    assert draft.quality_status == QUALITY_STATUS_DEGRADED
    assert draft.quality_reason == QUALITY_STATUS_REASON_SEMANTIC_DEGRADED
    assert draft.semantic_status == SEMANTIC_STATUS_DEGRADED


def test_quality_assessor_rejects_unready_packet() -> None:
    assessor = DeterministicQualityAssessor()

    with pytest.raises(QualityAssessmentUnavailableError, match="semantic_assessment_pending"):
        assessor.assess(packet(can_assess=False))


def test_validate_quality_assessment_output_accepts_canonical_source_refs() -> None:
    output = validate_quality_assessment_output(semantic_output(), packet())

    assert output.claim_assessments[0].source_ref_ids == ["source-1"]


def test_validate_quality_assessment_output_canonicalizes_alias_source_refs() -> None:
    output = validate_quality_assessment_output(alias_semantic_output(), packet())

    assert output.claim_assessments[0].source_ref_ids == ["source-1"]
    assert output.claim_assessments[0].rationale == "source-1 supports the claim."
    assert output.missing_high_signal_items[0].source_ref_ids == ["source-1"]
    assert output.missing_high_signal_items[0].description == "A decision near source-1 was missed."
    assert output.findings[0].references[0].id == "source-1"
    assert output.findings[0].message == "Source source-1 needs review."
    assert output.findings[0].details["source_ref"] == "source-1"
    assert output.overall_rationale == "source-1 supports the interpretation."


def test_validate_quality_assessment_output_rejects_unknown_claim_index() -> None:
    output = SemanticQualityAssessmentOutput.model_validate(
        {
            **semantic_output(),
            "claim_assessments": [{"claim_index": 2, "status": "supported"}],
        },
    )

    with pytest.raises(QualityAssessmentValidationError, match="unknown claim index"):
        validate_quality_assessment_output(output, packet())


def test_validate_quality_assessment_result_omits_unresolved_source_refs() -> None:
    result = validate_quality_assessment_result(recoverable_reference_defect_output(), packet())
    output = result.output

    assert result.reference_defect_count == 3
    assert [defect.field_path for defect in result.reference_defects] == [
        "claim_assessments[0].source_ref_ids[1]",
        "missing_high_signal_items[0].source_ref_ids[0]",
        "findings[0].references[1].id",
    ]
    assert output.claim_assessments[0].source_ref_ids == ["source-1"]
    assert output.missing_high_signal_items[0].source_ref_ids == []
    assert [reference.model_dump(mode="json") for reference in output.findings[0].references] == [
        {"kind": "source_ref", "id": "source-1"},
        {"kind": "claim", "id": "0"},
    ]
    persisted_payload = json.dumps(
        {
            "findings": [finding.model_dump(mode="json") for finding in output.findings],
            "claim_assessments": [assessment.model_dump(mode="json") for assessment in output.claim_assessments],
            "missing_high_signal_items": [item.model_dump(mode="json") for item in output.missing_high_signal_items],
        },
    )
    assert "activity_unit_id:111" not in persisted_payload


def test_validate_quality_assessment_output_omits_unknown_alias() -> None:
    candidate = {
        **semantic_output(),
        "claim_assessments": [
            {
                "claim_index": 0,
                "status": "supported",
                "source_ref_ids": ["s9999"],
            },
        ],
    }

    output = validate_quality_assessment_output(candidate, packet())

    assert output.claim_assessments[0].source_ref_ids == []


def test_pydantic_ai_quality_assessor_wraps_provider_failures() -> None:
    class FailingAgent:
        def __init__(self, _model: str, *, output_type: type) -> None:
            self.output_type = output_type

        def run_sync(self, _prompt: str) -> None:
            raise ProviderBodyShouldBeHiddenError()

    assessor = PydanticAIQualityAssessor("anthropic:model", agent_factory=FailingAgent)

    with pytest.raises(PydanticAIQualityAssessmentError, match="PydanticAI quality assessment failed"):
        assessor.assess(packet())
