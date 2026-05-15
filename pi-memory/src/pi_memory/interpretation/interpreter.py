"""Interpreter seam for session interpretation implementations."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

try:
    from pydantic_ai import Agent as PydanticAIAgent
except ImportError:
    PydanticAIAgent = None

from pi_memory.db import SOURCE_ORIGIN_LOCAL, SOURCE_ORIGIN_MIXED
from pi_memory.interpretation.contracts import (
    InterpretationCitation,
    InterpretationClaim,
    InterpretationOpenQuestion,
    InterpretationOutput,
)
from pi_memory.interpretation.packets import BoundedText, EpisodePacket, InterpretationPacket, SourceRef

INTERPRETATION_PROMPT_VERSION = "phase5b-session-interpretation-v1"
INTERPRETATION_SCHEMA_VERSION = 1
DETERMINISTIC_INTERPRETER_PROVIDER = "pi-memory"
DETERMINISTIC_INTERPRETER_MODEL = "deterministic-session-interpreter-v1"
DETERMINISTIC_INTERPRETER_MODE = "deterministic"
PYDANTIC_AI_INTERPRETER_MODE = "pydantic-ai"

_CLAIM_SOURCE_ORIGINS = frozenset((SOURCE_ORIGIN_LOCAL, SOURCE_ORIGIN_MIXED))
_PYDANTIC_AI_ERROR_MESSAGE = "PydanticAI session interpretation failed"

AgentFactory = Callable[..., Any]


@dataclass(frozen=True)
class InterpretationResult:
    """Interpreter result and metadata suitable for future snapshot recording."""

    output: InterpretationOutput
    model_metadata: Mapping[str, Any]
    prompt_version: str


class SessionInterpreter(Protocol):
    """Protocol implemented by session interpretation adapters."""

    def interpret(self, packet: InterpretationPacket) -> InterpretationResult:
        """Interpret a packet into structured output."""


class InterpreterError(Exception):
    """Base error for interpretation adapter failures."""


class InterpreterUnavailableError(InterpreterError):
    """Raised when a packet cannot be interpreted by the adapter."""

    @classmethod
    def packet_not_ready(cls, blocked_reason: str | None) -> InterpreterUnavailableError:
        reason = blocked_reason or "packet readiness does not allow model calls"
        return cls(f"Interpretation packet is not ready for interpretation: {reason}")

    @classmethod
    def no_claim_sources(cls) -> InterpreterUnavailableError:
        return cls("Interpretation packet has no local or mixed claim-source references")


class PydanticAIInterpreterError(InterpreterError):
    """Raised when a PydanticAI provider call fails during interpretation."""

    def __init__(self) -> None:
        super().__init__(_PYDANTIC_AI_ERROR_MESSAGE)


class PydanticAIDependencyError(InterpreterError):
    """Raised when PydanticAI is unavailable for interpreter construction."""

    def __init__(self) -> None:
        super().__init__("pydantic-ai is required for PydanticAISessionInterpreter")


class PydanticAISessionInterpreter:
    """Generic PydanticAI-backed session interpreter."""

    def __init__(
        self,
        model: str,
        *,
        prompt_version: str = INTERPRETATION_PROMPT_VERSION,
        agent_factory: AgentFactory | None = None,
    ) -> None:
        """Initialize a generic PydanticAI interpreter.

        Args:
            model: PydanticAI model string, including any provider prefix.
            prompt_version: Prompt version recorded with returned results.
            agent_factory: Optional factory for tests; defaults to pydantic_ai.Agent.
        """
        self.model = model
        self.prompt_version = prompt_version
        self._agent = _create_pydantic_ai_agent(model, agent_factory)

    def interpret(self, packet: InterpretationPacket) -> InterpretationResult:
        """Interpret a packet using PydanticAI synchronously."""
        _validate_packet_ready_for_interpretation(packet)
        prompt = _render_pydantic_ai_prompt(packet)
        try:
            run_result = self._agent.run_sync(prompt)
            output = _extract_pydantic_ai_output(run_result)
        except Exception as error:
            raise PydanticAIInterpreterError() from error
        return InterpretationResult(
            output=output,
            model_metadata=_pydantic_ai_model_metadata(self.model),
            prompt_version=self.prompt_version,
        )


@dataclass(frozen=True)
class DeterministicSessionInterpreter:
    """Deterministic test/development interpreter with no model dependencies."""

    prompt_version: str = INTERPRETATION_PROMPT_VERSION
    model_metadata: Mapping[str, Any] | None = None

    def interpret(self, packet: InterpretationPacket) -> InterpretationResult:
        """Produce deterministic structured output for a ready packet.

        Args:
            packet: Read-only interpretation packet built from Phase 5A rows.

        Returns:
            Deterministic interpretation result.

        Raises:
            InterpreterUnavailableError: If the packet is not ready or has no
                local/mixed claim-source references.
        """
        analysis_run_id = _ready_analysis_run_id(packet)
        claim_source = _first_required_claim_source(packet)

        output = InterpretationOutput(
            analysis_run_id=analysis_run_id,
            analyzed_through_entry_id=packet.readiness.analyzed_through_entry_id,
            analyzed_through_byte_offset=packet.readiness.analyzed_through_byte_offset,
            goal=_goal(packet),
            summary=_summary(packet),
            claims=[_claim(claim_source)],
            open_questions=_open_questions(packet, claim_source),
            citations=[InterpretationCitation(source_ref_id=claim_source.source_ref_id, usage="summary")],
        )
        return InterpretationResult(
            output=output,
            model_metadata=self.model_metadata if self.model_metadata is not None else _deterministic_model_metadata(),
            prompt_version=self.prompt_version,
        )


def _create_pydantic_ai_agent(model: str, agent_factory: AgentFactory | None) -> Any:
    factory = agent_factory if agent_factory is not None else _pydantic_ai_agent_factory()
    return factory(model, output_type=InterpretationOutput)


def _pydantic_ai_agent_factory() -> AgentFactory:
    if PydanticAIAgent is None:
        raise PydanticAIDependencyError()
    return cast(AgentFactory, PydanticAIAgent)


def _extract_pydantic_ai_output(run_result: Any) -> InterpretationOutput:
    output = getattr(run_result, "output", None)
    if isinstance(output, InterpretationOutput):
        return output
    if isinstance(output, Mapping):
        return InterpretationOutput.model_validate(output)
    return InterpretationOutput.model_validate(output)


def _render_pydantic_ai_prompt(packet: InterpretationPacket) -> str:
    prompt_packet = {
        "readiness": _readiness_prompt_data(packet),
        "episodes": [_episode_prompt_data(episode) for episode in packet.episode_packets],
    }
    packet_json = json.dumps(prompt_packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return (
        "You are interpreting a Pi coding-session memory packet. "
        "Use only the bounded packet data below. Do not infer from omitted raw transcript "
        "content or uncited tool output. Return an InterpretationOutput object that cites "
        "source_ref_id values from the packet. Claims must be supported by source_refs where "
        "claim_source_allowed is true and source_origin is local or mixed. Preserve these "
        "identity fields exactly: analysis_run_id, analyzed_through_entry_id, and "
        "analyzed_through_byte_offset.\n\n"
        f"Packet JSON:\n{packet_json}"
    )


def _readiness_prompt_data(packet: InterpretationPacket) -> Mapping[str, Any]:
    readiness = packet.readiness
    return {
        "stable_session_id": readiness.stable_session_id,
        "analysis_run_id": readiness.latest_analysis_run_id,
        "analyzed_through_entry_id": readiness.analyzed_through_entry_id,
        "analyzed_through_byte_offset": readiness.analyzed_through_byte_offset,
        "origin_counts": dict(readiness.origin_counts),
        "claim_source_activity_count": readiness.claim_source_activity_count,
        "activity_count": readiness.activity_count,
        "episode_count": readiness.episode_count,
        "manifest_count": readiness.manifest_count,
    }


def _episode_prompt_data(episode: EpisodePacket) -> Mapping[str, Any]:
    return {
        "episode_id": episode.episode_id,
        "manifest_id": episode.manifest_id,
        "ordinal": episode.ordinal,
        "status": episode.status,
        "close_reason": episode.close_reason,
        "byte_start": episode.byte_start,
        "byte_end": episode.byte_end,
        "activity_count": episode.activity_count,
        "message_count": episode.message_count,
        "tool_pair_count": episode.tool_pair_count,
        "included_ranges": list(episode.included_ranges),
        "omitted_ranges": list(episode.omitted_ranges),
        "origin_counts": dict(episode.origin_counts),
        "claim_source_activity_count": episode.claim_source_activity_count,
        "tool_result_text_byte_count": episode.tool_result_text_byte_count,
        "source_refs": [_source_ref_prompt_data(source_ref) for source_ref in episode.source_refs],
    }


def _source_ref_prompt_data(source_ref: SourceRef) -> Mapping[str, Any]:
    return {
        "source_ref_id": source_ref.source_ref_id,
        "activity_unit_id": source_ref.activity_unit_id,
        "episode_id": source_ref.episode_id,
        "episode_ordinal": source_ref.episode_ordinal,
        "activity_index": source_ref.activity_index,
        "activity_kind": source_ref.activity_kind,
        "source_origin": source_ref.source_origin,
        "claim_source_allowed": source_ref.claim_source_allowed,
        "source_entry_row_ids": list(source_ref.source_entry_row_ids),
        "byte_start": source_ref.byte_start,
        "byte_end": source_ref.byte_end,
        "excerpts": [_bounded_text_prompt_data(excerpt) for excerpt in source_ref.excerpts],
        "receipt_metadata": source_ref.receipt_metadata,
        "source_metadata": source_ref.source_metadata,
    }


def _bounded_text_prompt_data(excerpt: BoundedText) -> Mapping[str, Any]:
    return {
        "text": excerpt.text,
        "original_char_count": excerpt.original_char_count,
        "original_byte_count": excerpt.original_byte_count,
        "is_truncated": excerpt.is_truncated,
        "omitted_char_count": excerpt.omitted_char_count,
        "omitted_byte_count": excerpt.omitted_byte_count,
    }


def _ready_analysis_run_id(packet: InterpretationPacket) -> int:
    if not packet.readiness.can_call_model:
        raise InterpreterUnavailableError.packet_not_ready(packet.readiness.blocked_reason)
    analysis_run_id = packet.readiness.latest_analysis_run_id
    if analysis_run_id is None:
        raise InterpreterUnavailableError.packet_not_ready(packet.readiness.blocked_reason)
    return analysis_run_id


def _first_required_claim_source(packet: InterpretationPacket) -> SourceRef:
    claim_source = _first_claim_source(packet)
    if claim_source is None:
        raise InterpreterUnavailableError.no_claim_sources()
    return claim_source


def _validate_packet_ready_for_interpretation(packet: InterpretationPacket) -> None:
    _ready_analysis_run_id(packet)
    _first_required_claim_source(packet)


def _pydantic_ai_model_metadata(model: str) -> Mapping[str, Any]:
    return {
        "provider": _provider_from_model(model),
        "model": model,
        "mode": PYDANTIC_AI_INTERPRETER_MODE,
        "schema_version": INTERPRETATION_SCHEMA_VERSION,
    }


def _provider_from_model(model: str) -> str | None:
    provider, separator, _model_name = model.partition(":")
    return provider if separator else None


def _first_claim_source(packet: InterpretationPacket) -> SourceRef | None:
    for source_ref in _source_refs(packet):
        if _can_support_claim(source_ref):
            return source_ref
    return None


def _source_refs(packet: InterpretationPacket) -> tuple[SourceRef, ...]:
    return tuple(source_ref for episode_packet in packet.episode_packets for source_ref in episode_packet.source_refs)


def _can_support_claim(source_ref: SourceRef) -> bool:
    return source_ref.claim_source_allowed and source_ref.source_origin in _CLAIM_SOURCE_ORIGINS


def _goal(packet: InterpretationPacket) -> str:
    stable_session_id = packet.readiness.stable_session_id or "unknown session"
    return f"Interpret session {stable_session_id}."


def _summary(packet: InterpretationPacket) -> str:
    readiness = packet.readiness
    return (
        "Deterministic interpretation of "
        f"{readiness.episode_count} episode(s), "
        f"{readiness.activity_count} activity unit(s), and "
        f"{readiness.claim_source_activity_count} claim-source activity unit(s)."
    )


def _claim(source_ref: SourceRef) -> InterpretationClaim:
    return InterpretationClaim(
        source_ref_ids=[source_ref.source_ref_id],
        kind="knowledge",
        statement=("The session contains locally attributable activity suitable for interpretation."),
        confidence=0.5,
    )


def _open_questions(
    packet: InterpretationPacket,
    source_ref: SourceRef,
) -> list[InterpretationOpenQuestion]:
    omitted_range_count = sum(len(episode.omitted_ranges) for episode in packet.episode_packets)
    if omitted_range_count == 0:
        return []
    return [
        InterpretationOpenQuestion(
            question=f"What important context may be missing from {omitted_range_count} omitted range(s)?",
            source_ref_ids=[source_ref.source_ref_id],
        ),
    ]


def _deterministic_model_metadata() -> Mapping[str, Any]:
    return {
        "provider": DETERMINISTIC_INTERPRETER_PROVIDER,
        "model": DETERMINISTIC_INTERPRETER_MODEL,
        "mode": DETERMINISTIC_INTERPRETER_MODE,
        "schema_version": INTERPRETATION_SCHEMA_VERSION,
    }
