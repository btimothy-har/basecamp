"""Interpreter seam for session interpretation implementations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from pi_memory.db import SOURCE_ORIGIN_LOCAL, SOURCE_ORIGIN_MIXED
from pi_memory.interpretation.contracts import (
    InterpretationCitation,
    InterpretationClaim,
    InterpretationOpenQuestion,
    InterpretationOutput,
)
from pi_memory.interpretation.packets import InterpretationPacket, SourceRef

INTERPRETATION_PROMPT_VERSION = "phase5b-session-interpretation-v1"
INTERPRETATION_SCHEMA_VERSION = 1
DETERMINISTIC_INTERPRETER_PROVIDER = "pi-memory"
DETERMINISTIC_INTERPRETER_MODEL = "deterministic-session-interpreter-v1"
DETERMINISTIC_INTERPRETER_MODE = "deterministic"

_CLAIM_SOURCE_ORIGINS = frozenset((SOURCE_ORIGIN_LOCAL, SOURCE_ORIGIN_MIXED))


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
        if not packet.readiness.can_call_model:
            raise InterpreterUnavailableError.packet_not_ready(packet.readiness.blocked_reason)

        analysis_run_id = packet.readiness.latest_analysis_run_id
        if analysis_run_id is None:
            raise InterpreterUnavailableError.packet_not_ready(packet.readiness.blocked_reason)

        claim_source = _first_claim_source(packet)
        if claim_source is None:
            raise InterpreterUnavailableError.no_claim_sources()

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


def _first_claim_source(packet: InterpretationPacket) -> SourceRef | None:
    for source_ref in _source_refs(packet):
        if _can_support_claim(source_ref):
            return source_ref
    return None


def _source_refs(packet: InterpretationPacket) -> tuple[SourceRef, ...]:
    return tuple(
        source_ref
        for episode_packet in packet.episode_packets
        for source_ref in episode_packet.source_refs
    )


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
        statement=(
            "The session contains locally attributable activity suitable for "
            "interpretation."
        ),
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
