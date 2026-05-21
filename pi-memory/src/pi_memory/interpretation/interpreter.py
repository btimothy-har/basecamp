"""Interpreter seam for session interpretation implementations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from pi_memory.infra.llm import (
    AgentFactory,
    create_pydantic_ai_agent,
    pydantic_ai_model_metadata,
    run_pydantic_ai_agent,
    run_pydantic_ai_agent_sync,
)
from pi_memory.interpretation.contracts import (
    InterpretationCitation,
    InterpretationClaim,
    InterpretationOpenQuestion,
    InterpretationOutput,
    SourceRefAliases,
    build_source_ref_aliases,
    is_claim_source_eligible,
)
from pi_memory.interpretation.packets import ActivityPacket, BoundedText, EpisodePacket, InterpretationPacket, SourceRef

INTERPRETATION_PROMPT_VERSION = "phase5b-session-interpretation-v3"
INTERPRETATION_SCHEMA_VERSION = 1
TOOL_ACTIVITY_SUMMARY_PROMPT_VERSION = "phase5b-tool-activity-summary-v1"
TOOL_ACTIVITY_SUMMARY_SCHEMA_VERSION = 1
DETERMINISTIC_INTERPRETER_PROVIDER = "pi-memory"
DETERMINISTIC_INTERPRETER_MODEL = "deterministic-session-interpreter-v1"
DETERMINISTIC_INTERPRETER_MODE = "deterministic"
PYDANTIC_AI_INTERPRETER_MODE = "pydantic-ai"

_PYDANTIC_AI_ERROR_MESSAGE = "PydanticAI session interpretation failed"
_PYDANTIC_AI_TOOL_SUMMARY_ERROR_MESSAGE = "PydanticAI tool activity summarization failed"
_TOOL_SOURCE_RAW_LINE_CHAR_LIMIT = 12_000

ToolSummaryText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]


@dataclass(frozen=True)
class InterpretationResult:
    """Interpreter result and metadata suitable for future snapshot recording."""

    output: InterpretationOutput
    model_metadata: Mapping[str, Any]
    prompt_version: str


@dataclass(frozen=True)
class ToolActivitySourceEntry:
    """Canonical source row supplied to a tool activity summarizer."""

    row_id: int
    entry_id: str | None
    entry_type: str
    message_role: str | None
    byte_start: int
    byte_end: int
    raw_line: str


@dataclass(frozen=True)
class ToolActivitySummaryInput:
    """Source-backed input for summarizing one tool-pair activity."""

    activity_unit_id: int
    analysis_run_id: int
    ordinal: int
    tool_call_id: str | None
    tool_name: str | None
    is_error: bool | None
    source_entries: tuple[ToolActivitySourceEntry, ...]
    receipt_metadata: Mapping[str, Any]


class ToolActivitySummaryOutput(BaseModel):
    """Structured summary of one tool-pair activity."""

    model_config = ConfigDict(extra="forbid")

    summary: ToolSummaryText
    outcome: ToolSummaryText | None = None
    key_details: list[ToolSummaryText] = Field(default_factory=list, max_length=8)
    cited_source_entry_ids: list[int] = Field(min_length=1)


@dataclass(frozen=True)
class ToolActivitySummaryResult:
    """Tool activity summary and model metadata ready for persistence."""

    output: ToolActivitySummaryOutput
    model_metadata: Mapping[str, Any]
    prompt_version: str


class SessionInterpreter(Protocol):
    """Protocol implemented by session interpretation adapters."""

    def interpret(self, packet: InterpretationPacket) -> InterpretationResult:
        """Interpret a packet into structured output."""


class ToolActivitySummarizer(Protocol):
    """Protocol implemented by tool activity summary adapters."""

    def summarize(self, summary_input: ToolActivitySummaryInput) -> ToolActivitySummaryResult:
        """Summarize one tool-pair activity into structured output."""

    async def summarize_async(self, summary_input: ToolActivitySummaryInput) -> ToolActivitySummaryResult:
        """Summarize one tool-pair activity asynchronously."""


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


class PydanticAIToolSummaryError(InterpreterError):
    """Raised when a PydanticAI provider call fails during tool summarization."""

    def __init__(self) -> None:
        super().__init__(_PYDANTIC_AI_TOOL_SUMMARY_ERROR_MESSAGE)


class ToolActivitySummaryValidationError(InterpreterError):
    """Raised when a tool summary output is not valid for its source activity."""

    @classmethod
    def unknown_source_entry(cls, row_id: int) -> ToolActivitySummaryValidationError:
        return cls(f"Tool activity summary cites unknown source entry row id: {row_id}")


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
        self._agent = create_pydantic_ai_agent(
            model,
            InterpretationOutput,
            agent_factory=agent_factory,
            dependency_error_factory=PydanticAIDependencyError,
        )

    def interpret(self, packet: InterpretationPacket) -> InterpretationResult:
        """Interpret a packet using PydanticAI synchronously."""
        _validate_packet_ready_for_interpretation(packet)
        prompt = _render_pydantic_ai_prompt(packet)
        try:
            run_result = run_pydantic_ai_agent_sync(self._agent, prompt)
            output = _extract_pydantic_ai_output(run_result)
        except Exception as error:
            raise PydanticAIInterpreterError() from error
        return InterpretationResult(
            output=output,
            model_metadata=pydantic_ai_model_metadata(
                self.model,
                mode=PYDANTIC_AI_INTERPRETER_MODE,
                schema_version=INTERPRETATION_SCHEMA_VERSION,
            ),
            prompt_version=self.prompt_version,
        )


class PydanticAIToolActivitySummarizer:
    """Generic PydanticAI-backed single tool-pair activity summarizer."""

    def __init__(
        self,
        model: str,
        *,
        prompt_version: str = TOOL_ACTIVITY_SUMMARY_PROMPT_VERSION,
        agent_factory: AgentFactory | None = None,
    ) -> None:
        """Initialize a generic PydanticAI tool activity summarizer."""
        self.model = model
        self.prompt_version = prompt_version
        self._agent = create_pydantic_ai_agent(
            model,
            ToolActivitySummaryOutput,
            agent_factory=agent_factory,
            dependency_error_factory=PydanticAIDependencyError,
        )

    def summarize(self, summary_input: ToolActivitySummaryInput) -> ToolActivitySummaryResult:
        """Summarize one tool-pair activity using PydanticAI synchronously."""
        prompt = _render_tool_activity_summary_prompt(summary_input)
        try:
            run_result = run_pydantic_ai_agent_sync(self._agent, prompt)
            output = validate_tool_activity_summary_output(
                _extract_tool_activity_summary_output(run_result),
                summary_input,
            )
        except Exception as error:
            raise PydanticAIToolSummaryError() from error
        return ToolActivitySummaryResult(
            output=output,
            model_metadata=pydantic_ai_model_metadata(
                self.model,
                mode=PYDANTIC_AI_INTERPRETER_MODE,
                schema_version=TOOL_ACTIVITY_SUMMARY_SCHEMA_VERSION,
            ),
            prompt_version=self.prompt_version,
        )

    async def summarize_async(self, summary_input: ToolActivitySummaryInput) -> ToolActivitySummaryResult:
        """Summarize one tool-pair activity using one async PydanticAI call."""
        prompt = _render_tool_activity_summary_prompt(summary_input)
        try:
            run_result = await run_pydantic_ai_agent(self._agent, prompt)
            output = validate_tool_activity_summary_output(
                _extract_tool_activity_summary_output(run_result),
                summary_input,
            )
        except Exception as error:
            raise PydanticAIToolSummaryError() from error
        return ToolActivitySummaryResult(
            output=output,
            model_metadata=pydantic_ai_model_metadata(
                self.model,
                mode=PYDANTIC_AI_INTERPRETER_MODE,
                schema_version=TOOL_ACTIVITY_SUMMARY_SCHEMA_VERSION,
            ),
            prompt_version=self.prompt_version,
        )


@dataclass(frozen=True)
class DeterministicToolActivitySummarizer:
    """Deterministic test/development summarizer with no model dependencies."""

    prompt_version: str = TOOL_ACTIVITY_SUMMARY_PROMPT_VERSION
    model_metadata: Mapping[str, Any] | None = None

    def summarize(self, summary_input: ToolActivitySummaryInput) -> ToolActivitySummaryResult:
        """Produce deterministic structured output for one tool-pair activity."""
        return ToolActivitySummaryResult(
            output=_deterministic_tool_activity_output(summary_input),
            model_metadata=self.model_metadata
            if self.model_metadata is not None
            else _deterministic_tool_summary_model_metadata(),
            prompt_version=self.prompt_version,
        )

    async def summarize_async(self, summary_input: ToolActivitySummaryInput) -> ToolActivitySummaryResult:
        """Produce deterministic structured output for one tool-pair activity asynchronously."""
        return self.summarize(summary_input)


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


def _extract_pydantic_ai_output(run_result: Any) -> InterpretationOutput:
    output = getattr(run_result, "output", None)
    if isinstance(output, InterpretationOutput):
        return output
    return InterpretationOutput.model_validate(output)


def _extract_tool_activity_summary_output(run_result: Any) -> ToolActivitySummaryOutput:
    output = getattr(run_result, "output", None)
    if isinstance(output, ToolActivitySummaryOutput):
        return output
    return ToolActivitySummaryOutput.model_validate(output)


def validate_tool_activity_summary_output(
    output: ToolActivitySummaryOutput | Mapping[str, Any],
    summary_input: ToolActivitySummaryInput,
) -> ToolActivitySummaryOutput:
    """Validate a structured tool summary against its source activity."""
    model = (
        output if isinstance(output, ToolActivitySummaryOutput) else ToolActivitySummaryOutput.model_validate(output)
    )
    source_entry_ids = {entry.row_id for entry in summary_input.source_entries}
    for row_id in model.cited_source_entry_ids:
        if row_id not in source_entry_ids:
            raise ToolActivitySummaryValidationError.unknown_source_entry(row_id)
    return model


def _render_pydantic_ai_prompt(packet: InterpretationPacket) -> str:
    source_ref_aliases = build_source_ref_aliases(packet)
    prompt_packet = {
        "readiness": _readiness_prompt_data(packet),
        "episodes": [_episode_prompt_data(episode, source_ref_aliases) for episode in packet.episode_packets],
    }
    packet_json = json.dumps(prompt_packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return (
        "You are interpreting a Pi coding-session memory packet. "
        "Use only the bounded packet data below. Do not infer from omitted raw transcript "
        "content or uncited tool output. Return an InterpretationOutput object. Preserve these "
        "identity fields exactly: analysis_run_id, analyzed_through_entry_id, and "
        "analyzed_through_byte_offset.\n\n"
        "Claim extraction requirements:\n"
        "- If claim_source_activity_count is greater than zero, do not return an empty claims list.\n"
        "- Extract high-signal, source-backed claims about decisions, constraints, preferences, "
        "patterns, knowledge, and completed/deferred actions.\n"
        "- For substantial sessions, return roughly 8 to 20 claims; for short sessions, return at least one.\n"
        "- Citation ids in Packet JSON are short source-ref aliases. Copy them exactly; "
        "do not invent, shorten, or expand ids.\n"
        "- Every claim must cite one or more ids from an activity's claim_source_ref_ids.\n"
        "- Prefer specific engineering facts over generic claims like 'the session discussed X'.\n"
        "- Use citations for representative summary/open-question support; do not cite unavailable, "
        "failed, inherited-only, or non-claimable activities as claim support.\n\n"
        f"Packet JSON:\n{packet_json}"
    )


def _render_tool_activity_summary_prompt(summary_input: ToolActivitySummaryInput) -> str:
    prompt_packet = {
        "activity_unit_id": summary_input.activity_unit_id,
        "analysis_run_id": summary_input.analysis_run_id,
        "ordinal": summary_input.ordinal,
        "tool_call_id": summary_input.tool_call_id,
        "tool_name": summary_input.tool_name,
        "is_error": summary_input.is_error,
        "receipt_metadata": _bounded_json(summary_input.receipt_metadata),
        "source_entries": [_tool_source_entry_prompt_data(entry) for entry in summary_input.source_entries],
    }
    packet_json = json.dumps(prompt_packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return (
        "Summarize one Pi coding-session tool activity. Use only the source entries below. "
        "Do not infer from omitted content or outside knowledge. Return a ToolActivitySummaryOutput object. "
        "The summary should explain what this single tool call did and the relevant result in compact prose. "
        "Cite source entry row ids using cited_source_entry_ids; every cited id must come from source_entries.\n\n"
        f"Tool activity JSON:\n{packet_json}"
    )


def _tool_source_entry_prompt_data(entry: ToolActivitySourceEntry) -> Mapping[str, Any]:
    return {
        "row_id": entry.row_id,
        "entry_id": entry.entry_id,
        "entry_type": entry.entry_type,
        "message_role": entry.message_role,
        "byte_start": entry.byte_start,
        "byte_end": entry.byte_end,
        "raw_line": _bounded_raw_line(entry.raw_line),
    }


def _bounded_raw_line(value: str) -> Mapping[str, Any]:
    text = value[:_TOOL_SOURCE_RAW_LINE_CHAR_LIMIT]
    original_bytes = len(value.encode("utf-8"))
    text_bytes = len(text.encode("utf-8"))
    return {
        "text": text,
        "original_char_count": len(value),
        "original_byte_count": original_bytes,
        "is_truncated": len(value) > _TOOL_SOURCE_RAW_LINE_CHAR_LIMIT,
        "omitted_char_count": max(len(value) - len(text), 0),
        "omitted_byte_count": max(original_bytes - text_bytes, 0),
    }


def _bounded_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _bounded_json(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, tuple | list):
        return [_bounded_json(item) for item in value]
    if isinstance(value, str):
        return _bounded_metadata_string(value)
    if value is None or isinstance(value, bool | int | float):
        return value
    return _bounded_metadata_string(str(value))


def _bounded_metadata_string(value: str) -> str | Mapping[str, Any]:
    if len(value) <= 500:
        return value
    return {
        "omitted": True,
        "char_count": len(value),
        "byte_count": len(value.encode("utf-8")),
    }


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


def _episode_prompt_data(episode: EpisodePacket, source_ref_aliases: SourceRefAliases) -> Mapping[str, Any]:
    activities = [_activity_prompt_data(activity, source_ref_aliases) for activity in episode.included_activities]
    data: dict[str, Any] = {
        "ordinal": episode.ordinal,
        "status": episode.status,
        "close_reason": episode.close_reason,
        "activity_count": episode.activity_count,
        "message_count": episode.message_count,
        "tool_pair_count": episode.tool_pair_count,
        "claim_source_activity_count": episode.claim_source_activity_count,
        "activities": activities,
    }
    if not activities:
        data["source_refs"] = [
            _source_ref_prompt_data(source_ref, source_ref_aliases) for source_ref in episode.source_refs
        ]
    return data


def _activity_prompt_data(activity: ActivityPacket, source_ref_aliases: SourceRefAliases) -> Mapping[str, Any]:
    return {
        "activity_index": activity.activity_index,
        "kind": activity.kind,
        "source_origin": activity.source_origin,
        "claim_source_allowed": activity.claim_source_allowed,
        "tool_name": activity.tool_name,
        "is_error": activity.is_error,
        "activity_text": activity.activity_text,
        "activity_text_kind": activity.activity_text_kind,
        "activity_text_status": activity.activity_text_status,
        "source_ref_ids": [
            source_ref_aliases.alias_for(source_ref.source_ref_id) for source_ref in activity.source_refs
        ],
        "claim_source_ref_ids": [
            source_ref_aliases.alias_for(source_ref.source_ref_id)
            for source_ref in activity.source_refs
            if is_claim_source_eligible(source_ref)
        ],
    }


def _source_ref_prompt_data(source_ref: SourceRef, source_ref_aliases: SourceRefAliases) -> Mapping[str, Any]:
    return {
        "source_ref_id": source_ref_aliases.alias_for(source_ref.source_ref_id),
        "activity_index": source_ref.activity_index,
        "activity_kind": source_ref.activity_kind,
        "source_origin": source_ref.source_origin,
        "claim_source_allowed": source_ref.claim_source_allowed,
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


def _deterministic_tool_activity_output(summary_input: ToolActivitySummaryInput) -> ToolActivitySummaryOutput:
    source_entry_ids = [entry.row_id for entry in summary_input.source_entries]
    tool_name = summary_input.tool_name or "unknown tool"
    result_status = summary_input.receipt_metadata.get("result_status") or "unknown"
    return ToolActivitySummaryOutput(
        summary=f"Tool {tool_name} completed with result status {result_status}.",
        outcome=f"is_error={summary_input.is_error}",
        cited_source_entry_ids=source_entry_ids,
    )


def _first_claim_source(packet: InterpretationPacket) -> SourceRef | None:
    for source_ref in _source_refs(packet):
        if is_claim_source_eligible(source_ref):
            return source_ref
    return None


def _source_refs(packet: InterpretationPacket) -> tuple[SourceRef, ...]:
    return tuple(source_ref for episode_packet in packet.episode_packets for source_ref in episode_packet.source_refs)


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


def _deterministic_tool_summary_model_metadata() -> Mapping[str, Any]:
    return {
        "provider": DETERMINISTIC_INTERPRETER_PROVIDER,
        "model": "deterministic-tool-activity-summarizer-v1",
        "mode": DETERMINISTIC_INTERPRETER_MODE,
        "schema_version": TOOL_ACTIVITY_SUMMARY_SCHEMA_VERSION,
    }
