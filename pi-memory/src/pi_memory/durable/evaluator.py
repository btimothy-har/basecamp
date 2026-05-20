"""Candidate evaluation seam for durable-memory promotion."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any, Protocol, cast

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

try:
    from pydantic_ai import Agent as PydanticAIAgent
except ImportError:
    PydanticAIAgent = None

from pi_memory.db import DurableMemoryAuditEvent, DurableMemoryItem
from pi_memory.durable.contracts import (
    DURABLE_AUDIT_DETAIL_STRING_MAX_LENGTH,
    CandidateEvaluationOutput,
    CandidateMetricScore,
)
from pi_memory.durable.packets import DurableMemoryEvidencePacket, SourceRefEvidence

CANDIDATE_EVALUATION_PROMPT_VERSION = "phase6-candidate-evaluation-v1"
CANDIDATE_EVALUATION_SCHEMA_VERSION = 1
PYDANTIC_AI_CANDIDATE_EVALUATOR_MODE = "pydantic-ai"
DETERMINISTIC_CANDIDATE_EVALUATOR_MODE = "deterministic"
DETERMINISTIC_CANDIDATE_EVALUATOR_MODEL = "deterministic-candidate-evaluator-v1"
_PYDANTIC_AI_ERROR_MESSAGE = "PydanticAI candidate evaluation failed"
_PYDANTIC_AI_DEPENDENCY_ERROR_MESSAGE = "pydantic-ai is required for PydanticAICandidateEvaluator"
_SCHEMA_ERROR_MESSAGE = "Candidate evaluation output does not match the required schema"

AgentFactory = Callable[..., Any]


@dataclass(frozen=True)
class CandidateEvaluationResult:
    """Candidate evaluation output and model metadata."""

    output: CandidateEvaluationOutput
    model_metadata: Mapping[str, Any]
    prompt_version: str
    schema_version: int = CANDIDATE_EVALUATION_SCHEMA_VERSION

    @property
    def evaluation_json(self) -> dict[str, Any]:
        """Return JSON-safe data suitable for DurableMemoryItem.evaluation_json."""
        return {
            "output": self.output.model_dump(mode="json"),
            "model_metadata": dict(self.model_metadata),
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
        }


class CandidateEvaluator(Protocol):
    """Evaluates durable-memory candidates from bounded evidence packets."""

    def evaluate(self, packet: DurableMemoryEvidencePacket) -> CandidateEvaluationResult:
        """Evaluate a candidate synchronously."""
        ...

    async def evaluate_async(self, packet: DurableMemoryEvidencePacket) -> CandidateEvaluationResult:
        """Evaluate a candidate asynchronously."""
        ...


class CandidateEvaluationError(Exception):
    """Base error for candidate evaluation failures."""


class CandidateEvaluationValidationError(CandidateEvaluationError):
    """Raised when candidate evaluation output is invalid."""

    @classmethod
    def schema_error(cls) -> CandidateEvaluationValidationError:
        return cls(_SCHEMA_ERROR_MESSAGE)


class PydanticAICandidateEvaluationError(CandidateEvaluationError):
    """Raised when a PydanticAI call fails during candidate evaluation."""

    def __init__(self) -> None:
        super().__init__(_PYDANTIC_AI_ERROR_MESSAGE)


class PydanticAICandidateProviderError(PydanticAICandidateEvaluationError):
    """Raised when a PydanticAI provider call fails during candidate evaluation."""


class PydanticAIDependencyError(CandidateEvaluationError):
    """Raised when PydanticAI is unavailable for candidate evaluation."""

    def __init__(self) -> None:
        super().__init__(_PYDANTIC_AI_DEPENDENCY_ERROR_MESSAGE)


@dataclass(frozen=True)
class DeterministicCandidateEvaluator:
    """Deterministic test/development evaluator with no provider dependencies."""

    prompt_version: str = CANDIDATE_EVALUATION_PROMPT_VERSION
    model_metadata: Mapping[str, Any] | None = None

    def evaluate(self, packet: DurableMemoryEvidencePacket) -> CandidateEvaluationResult:
        """Produce a deterministic valid candidate evaluation."""
        output = CandidateEvaluationOutput(
            normalized_statement=packet.candidate.statement,
            memory_type=packet.candidate.claim_kind,
            scope="repo" if packet.repo_name else "session",
            metrics={
                "is_supported": _metric(0.9, "pass", "Candidate has bounded source evidence in the packet."),
                "is_vague": _metric(0.1, "pass", "Candidate statement is concrete enough for deterministic testing."),
                "is_durable": _metric(0.8, "pass", "Candidate is treated as durable for deterministic testing."),
                "is_transient": _metric(0.1, "pass", "Candidate is not treated as transient in deterministic mode."),
                "is_overgeneralized": _metric(0.1, "pass", "Candidate is not broadened beyond its statement."),
                "scope_fit": _metric(0.8, "pass", "Scope is derived from packet repository metadata."),
                "type_fit": _metric(0.8, "pass", "Memory type preserves the candidate claim kind."),
                "confidence": _metric(packet.candidate.confidence, "pass", "Confidence preserves the candidate score."),
            },
            overall_rationale="Deterministic evaluator preserved candidate fields and bounded metric scores.",
        )
        return CandidateEvaluationResult(
            output=output,
            model_metadata=self.model_metadata if self.model_metadata is not None else _deterministic_model_metadata(),
            prompt_version=self.prompt_version,
        )

    async def evaluate_async(self, packet: DurableMemoryEvidencePacket) -> CandidateEvaluationResult:
        """Produce a deterministic valid candidate evaluation asynchronously."""
        return self.evaluate(packet)


class PydanticAICandidateEvaluator:
    """PydanticAI-backed durable-memory candidate evaluator."""

    def __init__(
        self,
        model: str,
        *,
        prompt_version: str = CANDIDATE_EVALUATION_PROMPT_VERSION,
        agent_factory: AgentFactory | None = None,
    ) -> None:
        self.model = model
        self.prompt_version = prompt_version
        self._agent = _create_pydantic_ai_agent(model, CandidateEvaluationOutput, agent_factory)

    def evaluate(self, packet: DurableMemoryEvidencePacket) -> CandidateEvaluationResult:
        """Evaluate a candidate using one synchronous PydanticAI call."""
        prompt = render_candidate_evaluation_prompt(packet)
        try:
            run_result = self._agent.run_sync(prompt)
        except Exception as error:
            raise PydanticAICandidateProviderError() from error
        output = validate_candidate_evaluation_output(_extract_candidate_evaluation_output(run_result))
        return CandidateEvaluationResult(
            output=output,
            model_metadata=_pydantic_ai_model_metadata(self.model),
            prompt_version=self.prompt_version,
        )

    async def evaluate_async(self, packet: DurableMemoryEvidencePacket) -> CandidateEvaluationResult:
        """Evaluate a candidate using one async PydanticAI call."""
        prompt = render_candidate_evaluation_prompt(packet)
        try:
            run_result = await _run_pydantic_ai_agent(self._agent, prompt)
        except Exception as error:
            raise PydanticAICandidateProviderError() from error
        output = validate_candidate_evaluation_output(_extract_candidate_evaluation_output(run_result))
        return CandidateEvaluationResult(
            output=output,
            model_metadata=_pydantic_ai_model_metadata(self.model),
            prompt_version=self.prompt_version,
        )


def validate_candidate_evaluation_output(
    output: CandidateEvaluationOutput | Mapping[str, Any],
) -> CandidateEvaluationOutput:
    """Validate candidate evaluation output against the strict Pydantic contract."""
    try:
        return (
            output
            if isinstance(output, CandidateEvaluationOutput)
            else CandidateEvaluationOutput.model_validate(output)
        )
    except ValidationError as error:
        raise CandidateEvaluationValidationError.schema_error() from error


def candidate_evaluation_prompt_data(packet: DurableMemoryEvidencePacket) -> dict[str, Any]:
    """Convert a durable-memory evidence packet into JSON-safe prompt data."""
    return {
        "candidate": packet.candidate.model_dump(mode="json"),
        "eligibility": packet.eligibility.model_dump(mode="json"),
        "session_metadata": {
            "session_id": packet.session_id,
            "repo_name": packet.repo_name,
            "worktree_label": packet.worktree_label,
            "snapshot_id": packet.snapshot_id,
            "quality_report_id": packet.quality_report_id,
        },
        "source_evidence": [_source_ref_prompt_data(evidence) for evidence in packet.source_evidence],
        "omitted_source_count": packet.omitted_source_count,
    }


def render_candidate_evaluation_prompt(packet: DurableMemoryEvidencePacket) -> str:
    """Render the bounded PydanticAI prompt for candidate evaluation."""
    packet_json = json.dumps(
        candidate_evaluation_prompt_data(packet),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return (
        "You are evaluating one candidate for durable memory. Use only the bounded packet evidence below. "
        "Do not use raw transcript lines, outside knowledge, provider credentials, or omitted content. "
        "Return a CandidateEvaluationOutput object only.\n\n"
        "Hard boundaries:\n"
        "- Do not decide whether to promote, quarantine, reject, archive, supersede, or persist the candidate.\n"
        "- Do not assess relations to existing memories, duplicates, conflicts, or supersession.\n"
        "- Do not add reducer decisions, relation decisions, status changes, or audit events.\n"
        "- Normalize only the statement, memory_type, and scope from packet evidence.\n"
        "- Preserve the candidate meaning; do not invent facts beyond cited activity_text.\n\n"
        "Required output:\n"
        "- normalized_statement: concise source-backed statement.\n"
        "- memory_type: one of the allowed candidate claim kinds.\n"
        "- scope: session, repo, project, global, or unknown based only on packet metadata and evidence.\n"
        "- metrics: provide all eight metric scores with score 0.0-1.0, label pass/warning/fail, and concise reason.\n"
        "- overall_rationale: null or one short evidence-grounded sentence.\n\n"
        f"Durable-memory candidate packet JSON:\n{packet_json}"
    )


def persist_candidate_evaluation(
    session: Session,
    memory: DurableMemoryItem,
    result: CandidateEvaluationResult,
) -> DurableMemoryAuditEvent:
    """Persist a candidate evaluation and audit event without changing memory status."""
    memory.evaluation_json = result.evaluation_json
    audit_event = DurableMemoryAuditEvent(
        memory=memory,
        job_id=memory.job_id,
        event_type="candidate_evaluated",
        from_status=memory.status,
        to_status=memory.status,
        reason_code="candidate_evaluated",
        details_json=_audit_details(result),
    )
    session.add(audit_event)
    return audit_event


def _metric(score: float, label: str, reason: str) -> CandidateMetricScore:
    return CandidateMetricScore(score=score, label=label, reason=reason)


def _source_ref_prompt_data(evidence: SourceRefEvidence) -> dict[str, Any]:
    return {
        "source_ref_id": evidence.source_ref_id,
        "activity_unit_id": evidence.activity_unit_id,
        "source_origin": evidence.source_origin,
        "activity_kind": evidence.activity_kind,
        "activity_ordinal": evidence.activity_ordinal,
        "episode_ordinal": evidence.episode_ordinal,
        "activity_text": None if evidence.activity_text is None else asdict(evidence.activity_text),
        "citation_metadata": _json_safe(evidence.citation_metadata),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, tuple | list):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


def _create_pydantic_ai_agent(model: str, output_type: type[BaseModel], agent_factory: AgentFactory | None) -> Any:
    factory = agent_factory if agent_factory is not None else _pydantic_ai_agent_factory()
    return factory(model, output_type=output_type)


async def _run_pydantic_ai_agent(agent: Any, prompt: str) -> Any:
    # Support both async-capable PydanticAI agents and test doubles exposing run_sync only.
    run = getattr(agent, "run", None)
    if run is None:
        return await asyncio.to_thread(agent.run_sync, prompt)
    result = run(prompt)
    if inspect.isawaitable(result):
        return await result
    return result


def _pydantic_ai_agent_factory() -> AgentFactory:
    if PydanticAIAgent is None:
        raise PydanticAIDependencyError()
    return cast(AgentFactory, PydanticAIAgent)


def _extract_candidate_evaluation_output(run_result: Any) -> CandidateEvaluationOutput | Mapping[str, Any]:
    output = getattr(run_result, "output", None)
    if isinstance(output, CandidateEvaluationOutput | Mapping):
        return output
    return {}


def _pydantic_ai_model_metadata(model: str) -> Mapping[str, Any]:
    return {
        "provider": _provider_from_model(model),
        "model": model,
        "mode": PYDANTIC_AI_CANDIDATE_EVALUATOR_MODE,
        "schema_version": CANDIDATE_EVALUATION_SCHEMA_VERSION,
    }


def _deterministic_model_metadata() -> Mapping[str, Any]:
    return {
        "provider": "pi-memory",
        "model": DETERMINISTIC_CANDIDATE_EVALUATOR_MODEL,
        "mode": DETERMINISTIC_CANDIDATE_EVALUATOR_MODE,
        "schema_version": CANDIDATE_EVALUATION_SCHEMA_VERSION,
    }


def _provider_from_model(model: str) -> str | None:
    provider, separator, _model_name = model.partition(":")
    return provider if separator else None


def _audit_details(result: CandidateEvaluationResult) -> dict[str, Any]:
    model_metadata = result.model_metadata
    return {
        "prompt_version": result.prompt_version,
        "schema_version": result.schema_version,
        "provider": _bounded_audit_string(model_metadata.get("provider")),
        "model": _bounded_audit_string(model_metadata.get("model")),
        "mode": _bounded_audit_string(model_metadata.get("mode")),
    }


def _bounded_audit_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:DURABLE_AUDIT_DETAIL_STRING_MAX_LENGTH]


__all__ = [
    "CANDIDATE_EVALUATION_PROMPT_VERSION",
    "CANDIDATE_EVALUATION_SCHEMA_VERSION",
    "DETERMINISTIC_CANDIDATE_EVALUATOR_MODE",
    "DETERMINISTIC_CANDIDATE_EVALUATOR_MODEL",
    "PYDANTIC_AI_CANDIDATE_EVALUATOR_MODE",
    "AgentFactory",
    "CandidateEvaluationError",
    "CandidateEvaluationResult",
    "CandidateEvaluationValidationError",
    "CandidateEvaluator",
    "DeterministicCandidateEvaluator",
    "PydanticAICandidateEvaluationError",
    "PydanticAICandidateEvaluator",
    "PydanticAICandidateProviderError",
    "PydanticAIDependencyError",
    "candidate_evaluation_prompt_data",
    "persist_candidate_evaluation",
    "render_candidate_evaluation_prompt",
    "validate_candidate_evaluation_output",
]
