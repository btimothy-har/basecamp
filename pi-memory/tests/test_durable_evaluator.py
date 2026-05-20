from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pi_memory.durable.evaluator as evaluator_module
import pi_memory.durable.factory as durable_factory
import pytest
from pi_memory.db import (
    DURABLE_MEMORY_STATUS_CANDIDATE,
    SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
    Database,
    DurableMemoryAuditEvent,
    DurableMemoryItem,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
)
from pi_memory.durable import (
    CANDIDATE_EVALUATION_PROMPT_VERSION,
    CANDIDATE_EVALUATION_SCHEMA_VERSION,
    DETERMINISTIC_CANDIDATE_EVALUATOR_MODE,
    DETERMINISTIC_CANDIDATE_EVALUATOR_MODEL,
    PYDANTIC_AI_CANDIDATE_EVALUATOR_MODE,
    BoundedText,
    CandidateEvaluationOutput,
    CandidateEvaluationValidationError,
    DeterministicCandidateEvaluator,
    DurableMemoryCandidate,
    DurableMemoryEvidencePacket,
    PydanticAICandidateEvaluationError,
    PydanticAICandidateEvaluator,
    PydanticAIDependencyError,
    QualityEligibilityEnvelope,
    SourceRefEvidence,
    persist_candidate_evaluation,
    validate_candidate_evaluation_output,
)
from pi_memory.settings import MissingInterpretationModelError, Settings


class ProviderDetailsError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("provider details")


class RunResult:
    def __init__(self, output: Any) -> None:
        self.output = output


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


def candidate() -> DurableMemoryCandidate:
    return DurableMemoryCandidate(
        snapshot_id=1,
        quality_report_id=2,
        claim_index=0,
        claim_kind="decision",
        statement="Use durable-memory candidate evaluators.",
        confidence=0.87,
        source_ref_ids=["source-1"],
        content_hash="hash-1",
    )


def eligibility() -> QualityEligibilityEnvelope:
    return QualityEligibilityEnvelope(
        quality_report_id=2,
        snapshot_id=1,
        is_eligible=True,
        quality_status="healthy",
        semantic_status="passed",
        deterministic_status="passed",
        derivation_status="current",
        promotable=True,
        claim_count=1,
    )


def packet(*, session_cwd: str | None = "/repo/basecamp") -> DurableMemoryEvidencePacket:
    return DurableMemoryEvidencePacket(
        session_id="pi-session-1",
        session_cwd=session_cwd,
        worktree_label="wt-memory",
        snapshot_id=1,
        quality_report_id=2,
        candidate=candidate(),
        eligibility=eligibility(),
        source_evidence=(
            SourceRefEvidence(
                source_ref_id="source-1",
                activity_unit_id=10,
                source_origin="local",
                activity_kind="user_text",
                activity_ordinal=7,
                episode_ordinal=3,
                activity_text=BoundedText(
                    text="Evidence supports using durable-memory candidate evaluators.",
                    original_char_count=58,
                    original_byte_count=58,
                    is_truncated=False,
                    omitted_char_count=0,
                    omitted_byte_count=0,
                ),
                citation_metadata={"claim_index": 0, "source_ref_id": "source-1"},
            ),
        ),
        omitted_source_count=0,
    )


def evaluation_output() -> dict[str, Any]:
    metric = {"score": 0.9, "label": "pass", "reason": "Supported by source evidence."}
    return {
        "normalized_statement": "Use durable-memory candidate evaluators.",
        "memory_type": "decision",
        "scope": "cwd",
        "metrics": {
            "is_supported": metric,
            "is_vague": {"score": 0.1, "label": "pass", "reason": "The statement is concrete."},
            "is_durable": metric,
            "is_transient": {"score": 0.1, "label": "pass", "reason": "The statement is not transient."},
            "is_overgeneralized": {"score": 0.1, "label": "pass", "reason": "The statement is bounded."},
            "scope_fit": metric,
            "type_fit": metric,
            "confidence": metric,
        },
        "overall_rationale": "The candidate is source-backed and durable.",
    }


def test_deterministic_evaluator_returns_valid_output_and_evaluation_json() -> None:
    evaluator = DeterministicCandidateEvaluator()
    result = evaluator.evaluate(packet())

    assert result.output.normalized_statement == "Use durable-memory candidate evaluators."
    assert result.output.memory_type == "decision"
    assert result.output.scope == "cwd"
    assert set(result.output.metrics.model_dump()) == {
        "is_supported",
        "is_vague",
        "is_durable",
        "is_transient",
        "is_overgeneralized",
        "scope_fit",
        "type_fit",
        "confidence",
    }
    assert result.model_metadata == {
        "provider": "pi-memory",
        "model": DETERMINISTIC_CANDIDATE_EVALUATOR_MODEL,
        "mode": DETERMINISTIC_CANDIDATE_EVALUATOR_MODE,
        "schema_version": CANDIDATE_EVALUATION_SCHEMA_VERSION,
    }
    assert result.prompt_version == CANDIDATE_EVALUATION_PROMPT_VERSION
    assert result.evaluation_json["schema_version"] == CANDIDATE_EVALUATION_SCHEMA_VERSION
    assert result.evaluation_json["prompt_version"] == CANDIDATE_EVALUATION_PROMPT_VERSION
    assert result.evaluation_json["model_metadata"]["model"] == DETERMINISTIC_CANDIDATE_EVALUATOR_MODEL
    assert result.evaluation_json["output"]["metrics"]["is_supported"]["label"] == "pass"


def test_deterministic_evaluator_uses_session_scope_without_cwd_and_async_matches_sync() -> None:
    evaluator = DeterministicCandidateEvaluator()
    evidence_packet = packet(session_cwd=None)

    sync_result = evaluator.evaluate(evidence_packet)
    async_result = asyncio.run(evaluator.evaluate_async(evidence_packet))

    assert sync_result == async_result
    assert async_result.output.scope == "session"


@pytest.mark.parametrize(
    "bad_output",
    [
        {**evaluation_output(), "extra": "not allowed"},
        {
            **evaluation_output(),
            "metrics": {
                **evaluation_output()["metrics"],
                "is_supported": {"score": 0.5, "label": "ok", "reason": "Bad label."},
            },
        },
        {
            **evaluation_output(),
            "metrics": {
                **evaluation_output()["metrics"],
                "is_supported": {"score": 1.2, "label": "pass", "reason": "Bad score."},
            },
        },
    ],
)
def test_validate_candidate_evaluation_output_rejects_invalid_schema(bad_output: dict[str, Any]) -> None:
    with pytest.raises(CandidateEvaluationValidationError):
        validate_candidate_evaluation_output(bad_output)


def test_pydantic_ai_evaluator_uses_fake_agent_and_bounded_prompt() -> None:
    prompts: list[str] = []

    class FakeAgent:
        def __init__(self, model: str, *, output_type: type) -> None:
            self.model = model
            self.output_type = output_type

        def run_sync(self, prompt: str) -> RunResult:
            prompts.append(prompt)
            return RunResult(evaluation_output())

    evaluator = PydanticAICandidateEvaluator("anthropic:claude-haiku-4-5", agent_factory=FakeAgent)
    result = evaluator.evaluate(packet())

    assert isinstance(result.output, CandidateEvaluationOutput)
    assert result.model_metadata == {
        "provider": "anthropic",
        "model": "anthropic:claude-haiku-4-5",
        "mode": PYDANTIC_AI_CANDIDATE_EVALUATOR_MODE,
        "schema_version": CANDIDATE_EVALUATION_SCHEMA_VERSION,
    }
    assert "Durable-memory candidate packet JSON" in prompts[0]
    assert '"statement":"Use durable-memory candidate evaluators."' in prompts[0]
    assert '"session_cwd":"/repo/basecamp"' in prompts[0]
    assert "repo_name" not in prompts[0]
    assert '"activity_text":{"is_truncated":false' in prompts[0]
    assert "Evidence supports using durable-memory candidate evaluators." in prompts[0]
    assert "Do not decide whether to promote" in prompts[0]
    assert "Do not assess relations" in prompts[0]
    assert "relation decisions" in prompts[0]
    assert "raw transcript lines" in prompts[0]


def test_pydantic_ai_async_evaluator_uses_async_agent() -> None:
    prompts: list[str] = []

    class FakeAgent:
        def __init__(self, _model: str, *, output_type: type) -> None:
            self.output_type = output_type

        async def run(self, prompt: str) -> RunResult:
            prompts.append(prompt)
            return RunResult(evaluation_output())

    evaluator = PydanticAICandidateEvaluator("anthropic:claude-haiku-4-5", agent_factory=FakeAgent)

    result = asyncio.run(evaluator.evaluate_async(packet()))

    assert isinstance(result.output, CandidateEvaluationOutput)
    assert prompts and "Durable-memory candidate packet JSON" in prompts[0]


def test_pydantic_ai_async_evaluator_wraps_provider_exceptions() -> None:
    class FakeAgent:
        def __init__(self, _model: str, *, output_type: type) -> None:
            self.output_type = output_type

        async def run(self, _prompt: str) -> RunResult:
            raise ProviderDetailsError()

    evaluator = PydanticAICandidateEvaluator("anthropic:claude-haiku-4-5", agent_factory=FakeAgent)

    with pytest.raises(PydanticAICandidateEvaluationError) as error:
        asyncio.run(evaluator.evaluate_async(packet()))

    assert isinstance(error.value.__cause__, ProviderDetailsError)


def test_pydantic_ai_evaluator_requires_dependency_without_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evaluator_module, "PydanticAIAgent", None)

    with pytest.raises(PydanticAIDependencyError):
        PydanticAICandidateEvaluator("anthropic:claude-haiku-4-5")


def test_pydantic_ai_evaluator_rejects_invalid_provider_output_as_validation_error() -> None:
    class FakeAgent:
        def __init__(self, _model: str, *, output_type: type) -> None:
            self.output_type = output_type

        def run_sync(self, _prompt: str) -> RunResult:
            return RunResult({"normalized_statement": "missing required fields"})

    evaluator = PydanticAICandidateEvaluator("anthropic:claude-haiku-4-5", agent_factory=FakeAgent)

    with pytest.raises(CandidateEvaluationValidationError):
        evaluator.evaluate(packet())


def test_pydantic_ai_evaluator_wraps_provider_exceptions() -> None:
    class FakeAgent:
        def __init__(self, _model: str, *, output_type: type) -> None:
            self.output_type = output_type

        def run_sync(self, _prompt: str) -> RunResult:
            raise ProviderDetailsError()

    evaluator = PydanticAICandidateEvaluator("anthropic:claude-haiku-4-5", agent_factory=FakeAgent)

    with pytest.raises(PydanticAICandidateEvaluationError) as error:
        evaluator.evaluate(packet())

    assert isinstance(error.value.__cause__, ProviderDetailsError)
    assert "provider details" not in str(error.value)


def test_candidate_evaluator_factory_raises_when_no_model_configured(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "memory" / "config.json")

    with pytest.raises(MissingInterpretationModelError):
        durable_factory.create_candidate_evaluator(settings)


def test_candidate_evaluator_factory_uses_quality_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePydanticAICandidateEvaluator:
        def __init__(self, model: str) -> None:
            self.model = model

    monkeypatch.setattr(durable_factory, "PydanticAICandidateEvaluator", FakePydanticAICandidateEvaluator)
    settings = Settings(tmp_path / "memory" / "config.json")
    settings.update(
        interpretation_model="openai:interpretation-model",
        tool_summary_model="openai:summary-model",
        quality_model="anthropic:quality-model",
    )

    evaluator = durable_factory.create_candidate_evaluator(settings)

    assert isinstance(evaluator, FakePydanticAICandidateEvaluator)
    assert evaluator.model == "anthropic:quality-model"


def test_persist_candidate_evaluation_writes_json_and_audit_without_status_transition(database: Database) -> None:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1", cwd="/repo/basecamp")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            status=SESSION_INTERPRETATION_STATUS_COMPLETED,
            analyzed_through_byte_offset=10,
            claim_source_activity_count=1,
            interpretation_json={"claims": []},
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
            prompt_version="quality-v1",
        )
        memory = DurableMemoryItem(
            session=memory_session,
            snapshot=snapshot,
            quality_report=report,
            status=DURABLE_MEMORY_STATUS_CANDIDATE,
            claim_index=0,
            claim_kind="decision",
            statement="Use durable-memory candidate evaluators.",
            confidence=0.87,
            content_hash="hash-1",
        )
        session.add(memory)
        session.flush()
        original_status = memory.status

        result = DeterministicCandidateEvaluator().evaluate(packet())
        event = persist_candidate_evaluation(session, memory, result)
        session.flush()

        assert memory.status == original_status
        assert memory.evaluation_json == result.evaluation_json
        assert event.id is not None
        assert event.memory_id == memory.id
        assert event.event_type == "candidate_evaluated"
        assert event.from_status == original_status
        assert event.to_status == original_status
        assert event.reason_code == "candidate_evaluated"
        assert event.details_json == {
            "prompt_version": CANDIDATE_EVALUATION_PROMPT_VERSION,
            "schema_version": CANDIDATE_EVALUATION_SCHEMA_VERSION,
            "provider": "pi-memory",
            "model": DETERMINISTIC_CANDIDATE_EVALUATOR_MODEL,
            "mode": DETERMINISTIC_CANDIDATE_EVALUATOR_MODE,
        }
        assert session.get(DurableMemoryAuditEvent, event.id) is event
