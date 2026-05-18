from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from pi_memory.interpretation import BoundedText
from pi_memory.quality import (
    DETERMINISTIC_QUALITY_ASSESSOR_MODE,
    PYDANTIC_AI_QUALITY_ASSESSOR_MODE,
    QUALITY_BOUNDED_TEXT_MAX_LENGTH,
    QUALITY_CLAIM_ASSESSMENTS_MAX_LENGTH,
    QUALITY_MISSING_HIGH_SIGNAL_ITEMS_MAX_LENGTH,
    QUALITY_SEMANTIC_FINDINGS_MAX_LENGTH,
    QUALITY_STATUS_HEALTHY,
    QUALITY_STATUS_NOT_ASSESSED,
    QUALITY_STATUS_REASON_SEMANTIC_ASSESSMENT_PENDING,
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


def packet(*, can_assess: bool = True) -> QualityPacket:
    deterministic_report = report()
    return QualityPacket(
        snapshot_id=1,
        session_metadata={"session_row_id": 1, "stable_session_id": "pi-session-1"},
        snapshot_metadata={"snapshot_id": 1, "analysis_run_id": 2},
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
    assert draft.model_metadata == {
        "provider": "anthropic",
        "model": "anthropic:claude-haiku-4-5",
        "mode": PYDANTIC_AI_QUALITY_ASSESSOR_MODE,
        "schema_version": 1,
    }
    assert "Quality packet JSON" in prompts[0]
    assert f"<= {QUALITY_BOUNDED_TEXT_MAX_LENGTH} characters" in prompts[0]
    assert f"findings must contain <= {QUALITY_SEMANTIC_FINDINGS_MAX_LENGTH} items" in prompts[0]
    assert f"claim_assessments must contain <= {QUALITY_CLAIM_ASSESSMENTS_MAX_LENGTH} items" in prompts[0]
    assert (
        f"missing_high_signal_items must contain <= {QUALITY_MISSING_HIGH_SIGNAL_ITEMS_MAX_LENGTH} items" in prompts[0]
    )
    assert "overall_rationale may be null" in prompts[0]
    assert "raw_line" not in prompts[0]
    assert os.environ["ANTHROPIC_API_KEY"] not in prompts[0]


def test_pydantic_ai_quality_assessor_supports_async_agents() -> None:
    class FakeAsyncAgent:
        def __init__(self, _model: str, *, output_type: type) -> None:
            self.output_type = output_type

        async def run(self, _prompt: str) -> RunResult:
            return RunResult(semantic_output("degraded"))

    assessor = PydanticAIQualityAssessor("openai:gpt-fast", agent_factory=FakeAsyncAgent)
    draft = asyncio.run(assessor.assess_async(packet()))

    assert draft.quality_status == "degraded"
    assert draft.quality_reason == "semantic_degraded"
    assert draft.promotable is False


def test_deterministic_quality_assessor_returns_healthy_report() -> None:
    draft = DeterministicQualityAssessor().assess(packet())

    assert draft.quality_status == QUALITY_STATUS_HEALTHY
    assert draft.model_metadata["mode"] == DETERMINISTIC_QUALITY_ASSESSOR_MODE
    assert draft.promotable is True


def test_quality_assessor_rejects_unready_packet() -> None:
    assessor = DeterministicQualityAssessor()

    with pytest.raises(QualityAssessmentUnavailableError, match="semantic_assessment_pending"):
        assessor.assess(packet(can_assess=False))


def test_validate_quality_assessment_output_rejects_unknown_claim_index() -> None:
    output = SemanticQualityAssessmentOutput.model_validate(
        {
            **semantic_output(),
            "claim_assessments": [{"claim_index": 2, "status": "supported"}],
        },
    )

    with pytest.raises(QualityAssessmentValidationError, match="unknown claim index"):
        validate_quality_assessment_output(output, packet())


def test_validate_quality_assessment_output_rejects_unknown_source_ref() -> None:
    candidate = {
        **semantic_output(),
        "missing_high_signal_items": [
            {
                "kind": "decision",
                "description": "Missed decision.",
                "source_ref_ids": ["missing-source"],
            },
        ],
    }

    with pytest.raises(QualityAssessmentValidationError, match="unknown source_ref_id"):
        validate_quality_assessment_output(candidate, packet())


def test_pydantic_ai_quality_assessor_wraps_provider_failures() -> None:
    class FailingAgent:
        def __init__(self, _model: str, *, output_type: type) -> None:
            self.output_type = output_type

        def run_sync(self, _prompt: str) -> None:
            raise ProviderBodyShouldBeHiddenError()

    assessor = PydanticAIQualityAssessor("anthropic:model", agent_factory=FailingAgent)

    with pytest.raises(PydanticAIQualityAssessmentError, match="PydanticAI quality assessment failed"):
        assessor.assess(packet())
