from __future__ import annotations

import socket
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from pi_memory.db import SOURCE_ORIGIN_INHERITED, SOURCE_ORIGIN_LOCAL, SOURCE_ORIGIN_MIXED
from pi_memory.interpretation import (
    DETERMINISTIC_INTERPRETER_MODE,
    DETERMINISTIC_INTERPRETER_MODEL,
    DETERMINISTIC_INTERPRETER_PROVIDER,
    INTERPRETATION_PROMPT_VERSION,
    INTERPRETATION_SCHEMA_VERSION,
    PYDANTIC_AI_INTERPRETER_MODE,
    TOOL_ACTIVITY_SUMMARY_PROMPT_VERSION,
    TOOL_ACTIVITY_SUMMARY_SCHEMA_VERSION,
    ActivityPacket,
    BoundedText,
    DeterministicSessionInterpreter,
    DeterministicToolActivitySummarizer,
    EpisodePacket,
    InterpretationOutput,
    InterpretationPacket,
    InterpretationReadiness,
    InterpretationResult,
    InterpreterUnavailableError,
    PydanticAIInterpreterError,
    PydanticAISessionInterpreter,
    PydanticAIToolActivitySummarizer,
    PydanticAIToolSummaryError,
    SessionInterpreter,
    SourceRef,
    ToolActivitySourceEntry,
    ToolActivitySummarizer,
    ToolActivitySummaryInput,
    ToolActivitySummaryOutput,
    ToolActivitySummaryResult,
    ToolActivitySummaryValidationError,
    build_episode_interpretation_packet,
    validate_interpretation_output,
    validate_tool_activity_summary_output,
)


def source_ref(
    source_ref_id: str,
    *,
    source_origin: str = SOURCE_ORIGIN_LOCAL,
    claim_source_allowed: bool = True,
) -> SourceRef:
    return SourceRef(
        source_ref_id=source_ref_id,
        activity_unit_id=10,
        episode_id=20,
        episode_ordinal=0,
        activity_index=1,
        activity_kind="message",
        source_origin=source_origin,
        claim_source_allowed=claim_source_allowed,
        source_entry_row_ids=(30,),
        byte_start=40,
        byte_end=50,
        excerpts=(
            BoundedText(
                text="source excerpt",
                original_char_count=14,
                original_byte_count=14,
                is_truncated=False,
                omitted_char_count=0,
                omitted_byte_count=0,
            ),
        ),
        receipt_metadata={},
        source_metadata={},
    )


def activity_packet(source_ref: SourceRef) -> ActivityPacket:
    return ActivityPacket(
        activity_unit_id=source_ref.activity_unit_id,
        episode_id=source_ref.episode_id,
        episode_ordinal=source_ref.episode_ordinal,
        activity_index=source_ref.activity_index,
        sequence=1,
        kind=source_ref.activity_kind,
        source_origin=source_ref.source_origin,
        claim_source_allowed=source_ref.claim_source_allowed,
        source_entry_row_ids=source_ref.source_entry_row_ids,
        byte_start=source_ref.byte_start,
        byte_end=source_ref.byte_end,
        message_role="user",
        tool_call_id=None,
        tool_name=None,
        is_error=None,
        text_char_count=25,
        result_text_byte_count=0,
        result_text_line_count=0,
        activity_text="User message:\nUse aliases.",
        activity_text_kind="message",
        activity_text_status="completed",
        activity_text_metadata={},
        receipt_metadata={},
        source_metadata={},
        source_refs=(source_ref,),
    )


def packet(
    *source_refs: SourceRef,
    omitted_ranges: tuple[dict[str, int], ...] = (),
) -> InterpretationPacket:
    return InterpretationPacket(
        session_metadata={"session_row_id": 1, "stable_session_id": "session-1"},
        transcript_metadata={"transcript_id": 2},
        source_analysis_metadata={"analysis_run_id": 123},
        readiness=InterpretationReadiness(
            session_row_id=1,
            stable_session_id="session-1",
            transcript_id=2,
            latest_analysis_run_id=123,
            requested_analysis_run_id=None,
            is_stale=False,
            is_ready=True,
            blocked_reason=None,
            origin_counts={
                "local_activity_count": 1,
                "inherited_activity_count": 0,
                "mixed_activity_count": 0,
                "unknown_activity_count": 0,
            },
            claim_source_activity_count=1,
            activity_count=1,
            episode_count=1,
            manifest_count=1,
            analyzed_through_entry_id=99,
            analyzed_through_byte_offset=456,
        ),
        episode_packets=(
            EpisodePacket(
                episode_id=20,
                manifest_id=21,
                ordinal=0,
                status="closed",
                close_reason=None,
                byte_start=0,
                byte_end=100,
                activity_count=len(source_refs),
                message_count=len(source_refs),
                tool_pair_count=0,
                included_ranges=(),
                omitted_ranges=omitted_ranges,
                origin_counts={},
                claim_source_activity_count=len(source_refs),
                tool_result_text_byte_count=0,
                included_activities=(),
                source_refs=source_refs,
            ),
        ),
    )


class NetworkAccessError(AssertionError):
    """Raised if deterministic interpretation attempts network access."""


class FakePydanticAgent:
    def __init__(self, output: Any = None, error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.prompts: list[str] = []

    def run_sync(self, prompt: str) -> SimpleNamespace:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(output=self.output)


class FakePydanticAgentFactory:
    def __init__(self, agent: FakePydanticAgent) -> None:
        self.agent = agent
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, model: str, **kwargs: Any) -> FakePydanticAgent:
        self.calls.append((model, kwargs))
        return self.agent


def interpretation_output(source_packet: InterpretationPacket, source_ref_id: str) -> InterpretationOutput:
    return InterpretationOutput(
        analysis_run_id=source_packet.readiness.latest_analysis_run_id or 0,
        analyzed_through_entry_id=source_packet.readiness.analyzed_through_entry_id,
        analyzed_through_byte_offset=source_packet.readiness.analyzed_through_byte_offset,
        goal="Interpret the session.",
        summary="The session has a bounded source excerpt.",
        claims=[
            {
                "source_ref_ids": [source_ref_id],
                "kind": "knowledge",
                "statement": "The bounded source supports a claim.",
                "confidence": 0.75,
            },
        ],
        citations=[{"source_ref_id": source_ref_id, "usage": "summary"}],
    )


def interpret_with_protocol(
    interpreter: SessionInterpreter,
    source_packet: InterpretationPacket,
) -> InterpretationResult:
    return interpreter.interpret(source_packet)


def tool_summary_input(activity_unit_id: int = 10) -> ToolActivitySummaryInput:
    return ToolActivitySummaryInput(
        activity_unit_id=activity_unit_id,
        analysis_run_id=123,
        ordinal=2,
        tool_call_id="call-1",
        tool_name="bash",
        is_error=False,
        source_entries=(
            ToolActivitySourceEntry(
                row_id=30,
                entry_id="call-entry",
                entry_type="message",
                message_role="assistant",
                byte_start=100,
                byte_end=200,
                raw_line='{"message":{"content":[{"type":"toolCall","name":"bash","arguments":{"command":"pwd"}}]}}',
            ),
            ToolActivitySourceEntry(
                row_id=31,
                entry_id="result-entry",
                entry_type="message",
                message_role="toolResult",
                byte_start=200,
                byte_end=300,
                raw_line='{"message":{"role":"toolResult","content":"/repo","isError":false}}',
            ),
        ),
        receipt_metadata={"result_status": "success", "argument_keys": ["command"]},
    )


def summarize_with_protocol(
    summarizer: ToolActivitySummarizer,
    summary_input: ToolActivitySummaryInput,
) -> ToolActivitySummaryResult:
    return summarizer.summarize(summary_input)


def test_protocol_result_metadata_shape() -> None:
    interpreter = DeterministicSessionInterpreter()

    result = interpret_with_protocol(interpreter, packet(source_ref("local-ref")))

    assert isinstance(result, InterpretationResult)
    assert isinstance(result.output, InterpretationOutput)
    assert result.prompt_version == INTERPRETATION_PROMPT_VERSION
    assert result.model_metadata == {
        "provider": DETERMINISTIC_INTERPRETER_PROVIDER,
        "model": DETERMINISTIC_INTERPRETER_MODEL,
        "mode": DETERMINISTIC_INTERPRETER_MODE,
        "schema_version": INTERPRETATION_SCHEMA_VERSION,
    }


def test_tool_summary_protocol_result_metadata_shape() -> None:
    summarizer = DeterministicToolActivitySummarizer()
    summary_input = tool_summary_input()

    result = summarize_with_protocol(summarizer, summary_input)

    assert isinstance(result, ToolActivitySummaryResult)
    assert isinstance(result.output, ToolActivitySummaryOutput)
    assert result.prompt_version == TOOL_ACTIVITY_SUMMARY_PROMPT_VERSION
    assert result.model_metadata == {
        "provider": DETERMINISTIC_INTERPRETER_PROVIDER,
        "model": "deterministic-tool-activity-summarizer-v1",
        "mode": DETERMINISTIC_INTERPRETER_MODE,
        "schema_version": TOOL_ACTIVITY_SUMMARY_SCHEMA_VERSION,
    }
    assert result.output.cited_source_entry_ids == [30, 31]
    assert validate_tool_activity_summary_output(result.output, summary_input) is result.output


def test_tool_summary_contract_rejects_unknown_source_entry_id() -> None:
    summary_input = tool_summary_input()
    output = ToolActivitySummaryOutput(summary="The tool returned the repository path.", cited_source_entry_ids=[999])

    with pytest.raises(ToolActivitySummaryValidationError, match="999"):
        validate_tool_activity_summary_output(output, summary_input)


def test_custom_prompt_and_model_metadata_are_preserved() -> None:
    interpreter = DeterministicSessionInterpreter(prompt_version="test-prompt", model_metadata={})

    result = interpreter.interpret(packet(source_ref("local-ref")))

    assert result.prompt_version == "test-prompt"
    assert result.model_metadata == {}


def test_deterministic_interpreter_returns_valid_output() -> None:
    source_packet = packet(source_ref("local-ref"))

    result = DeterministicSessionInterpreter().interpret(source_packet)

    assert result.output.analysis_run_id == source_packet.readiness.latest_analysis_run_id
    assert result.output.analyzed_through_entry_id == source_packet.readiness.analyzed_through_entry_id
    assert result.output.analyzed_through_byte_offset == source_packet.readiness.analyzed_through_byte_offset
    assert result.output.claims[0].source_ref_ids == ["local-ref"]
    assert result.output.citations[0].source_ref_id == "local-ref"
    validated = validate_interpretation_output(result.output, source_packet)
    assert validated.output is result.output


def test_deterministic_interpreter_uses_first_local_or_mixed_claim_source() -> None:
    source_packet = packet(
        source_ref("inherited-ref", source_origin=SOURCE_ORIGIN_INHERITED),
        source_ref("mixed-ref", source_origin=SOURCE_ORIGIN_MIXED),
        source_ref("local-ref", source_origin=SOURCE_ORIGIN_LOCAL),
    )

    result = DeterministicSessionInterpreter().interpret(source_packet)

    assert result.output.claims[0].source_ref_ids == ["mixed-ref"]
    validate_interpretation_output(result.output, source_packet)


def test_deterministic_interpreter_reports_omitted_ranges_as_open_question() -> None:
    source_packet = packet(source_ref("local-ref"), omitted_ranges=({"byte_start": 1, "byte_end": 2},))

    result = DeterministicSessionInterpreter().interpret(source_packet)

    assert result.output.open_questions[0].source_ref_ids == ["local-ref"]
    assert "1 omitted range" in result.output.open_questions[0].question
    validate_interpretation_output(result.output, source_packet)


def test_deterministic_interpreter_has_no_network_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_socket(*_args: object, **_kwargs: object) -> socket.socket:
        raise NetworkAccessError

    monkeypatch.setattr(socket, "socket", fail_socket)

    result = DeterministicSessionInterpreter().interpret(packet(source_ref("local-ref")))

    assert result.model_metadata["mode"] == "deterministic"


def test_non_interpretable_packet_raises_clear_error() -> None:
    source_packet = packet(source_ref("local-ref"))
    not_ready = replace(
        source_packet,
        readiness=replace(
            source_packet.readiness,
            is_ready=False,
            blocked_reason="phase_5a_not_ready",
        ),
    )

    with pytest.raises(InterpreterUnavailableError, match="phase_5a_not_ready"):
        DeterministicSessionInterpreter().interpret(not_ready)


def test_no_claim_source_refs_raise_clear_error() -> None:
    source_packet = packet(
        source_ref(
            "inherited-ref",
            source_origin=SOURCE_ORIGIN_INHERITED,
            claim_source_allowed=True,
        ),
    )

    with pytest.raises(InterpreterUnavailableError, match="no local or mixed claim-source"):
        DeterministicSessionInterpreter().interpret(source_packet)


def test_no_source_refs_raise_clear_error() -> None:
    source_packet = packet()

    with pytest.raises(InterpreterUnavailableError, match="no local or mixed claim-source"):
        DeterministicSessionInterpreter().interpret(source_packet)


def test_pydantic_ai_interpreter_uses_agent_factory_and_returns_output() -> None:
    source_packet = packet(source_ref("local-ref"))
    output = interpretation_output(source_packet, "local-ref")
    agent = FakePydanticAgent(output=output)
    factory = FakePydanticAgentFactory(agent)
    interpreter = PydanticAISessionInterpreter("test-provider:test-model", agent_factory=factory)

    result = interpreter.interpret(source_packet)

    assert factory.calls == [("test-provider:test-model", {"output_type": InterpretationOutput})]
    assert result.output is output
    assert result.prompt_version == INTERPRETATION_PROMPT_VERSION
    assert result.model_metadata == {
        "provider": "test-provider",
        "model": "test-provider:test-model",
        "mode": PYDANTIC_AI_INTERPRETER_MODE,
        "schema_version": INTERPRETATION_SCHEMA_VERSION,
    }
    validate_interpretation_output(result.output, source_packet)


def test_pydantic_ai_interpreter_accepts_mapping_output() -> None:
    source_packet = packet(source_ref("local-ref"))
    output = interpretation_output(source_packet, "local-ref")
    agent = FakePydanticAgent(output=output.model_dump(mode="json"))
    interpreter = PydanticAISessionInterpreter(
        "test-provider:test-model",
        agent_factory=FakePydanticAgentFactory(agent),
    )

    result = interpreter.interpret(source_packet)

    assert result.output == output
    validate_interpretation_output(result.output, source_packet)


def test_pydantic_ai_tool_summarizer_uses_agent_factory_and_returns_output() -> None:
    summary_input = tool_summary_input()
    output = ToolActivitySummaryOutput(
        summary="The bash tool returned the repository path.",
        outcome="success",
        key_details=["The observed output was /repo."],
        cited_source_entry_ids=[30, 31],
    )
    agent = FakePydanticAgent(output=output)
    factory = FakePydanticAgentFactory(agent)
    summarizer = PydanticAIToolActivitySummarizer("test-provider:test-model", agent_factory=factory)

    result = summarizer.summarize(summary_input)

    assert factory.calls == [("test-provider:test-model", {"output_type": ToolActivitySummaryOutput})]
    assert result.output is output
    assert result.prompt_version == TOOL_ACTIVITY_SUMMARY_PROMPT_VERSION
    assert result.model_metadata == {
        "provider": "test-provider",
        "model": "test-provider:test-model",
        "mode": PYDANTIC_AI_INTERPRETER_MODE,
        "schema_version": TOOL_ACTIVITY_SUMMARY_SCHEMA_VERSION,
    }
    validate_tool_activity_summary_output(result.output, summary_input)


def test_pydantic_ai_tool_summarizer_renders_source_backed_prompt() -> None:
    summary_input = tool_summary_input()
    output = ToolActivitySummaryOutput(summary="The tool returned /repo.", cited_source_entry_ids=[30, 31])
    agent = FakePydanticAgent(output=output)
    summarizer = PydanticAIToolActivitySummarizer(
        "plain-model-name",
        prompt_version="tool-prompt-v2",
        agent_factory=FakePydanticAgentFactory(agent),
    )

    result = summarizer.summarize(summary_input)

    assert result.prompt_version == "tool-prompt-v2"
    assert result.model_metadata["provider"] is None
    prompt = agent.prompts[0]
    assert "Tool activity JSON" in prompt
    assert "Tool activity batch JSON" not in prompt
    assert "cited_source_entry_ids" in prompt
    assert "pwd" in prompt
    assert "/repo" in prompt
    assert "outside knowledge" in prompt


@pytest.mark.asyncio
async def test_pydantic_ai_tool_summarizer_async_returns_one_summary() -> None:
    summary_input = tool_summary_input()
    output = ToolActivitySummaryOutput(summary="The async tool returned /repo.", cited_source_entry_ids=[30, 31])
    agent = FakePydanticAgent(output=output)
    summarizer = PydanticAIToolActivitySummarizer(
        "test-provider:test-model",
        agent_factory=FakePydanticAgentFactory(agent),
    )

    result = await summarizer.summarize_async(summary_input)

    assert result.output is output
    assert len(agent.prompts) == 1


def test_pydantic_ai_interpreter_renders_bounded_packet_prompt_only() -> None:
    canonical_id = "ar1:ep0:act196:entries240"
    canonical_ref = source_ref(canonical_id)
    base_packet = packet(canonical_ref)
    episode = base_packet.episode_packets[0]
    source_packet = replace(
        base_packet,
        session_metadata={"secret": "SESSION_METADATA_SHOULD_NOT_APPEAR"},
        transcript_metadata={"secret": "TRANSCRIPT_METADATA_SHOULD_NOT_APPEAR"},
        source_analysis_metadata={"secret": "ANALYSIS_METADATA_SHOULD_NOT_APPEAR"},
        episode_packets=(replace(episode, included_activities=(activity_packet(canonical_ref),)),),
    )
    output = interpretation_output(source_packet, canonical_id)
    agent = FakePydanticAgent(output=output)
    interpreter = PydanticAISessionInterpreter(
        "plain-model-name",
        prompt_version="test-prompt-v2",
        agent_factory=FakePydanticAgentFactory(agent),
    )

    result = interpreter.interpret(source_packet)

    assert result.prompt_version == "test-prompt-v2"
    assert result.model_metadata["provider"] is None
    prompt = agent.prompts[0]
    assert "source excerpt" not in prompt
    assert canonical_id not in prompt
    assert '"source_ref_ids":["s0001"]' in prompt
    assert '"claim_source_ref_ids":["s0001"]' in prompt
    assert "short source-ref aliases" in prompt
    assert "do not return an empty claims list" in prompt
    assert "analysis_run_id" in prompt
    assert "analyzed_through_byte_offset" in prompt
    assert "SESSION_METADATA_SHOULD_NOT_APPEAR" not in prompt
    assert "TRANSCRIPT_METADATA_SHOULD_NOT_APPEAR" not in prompt
    assert "ANALYSIS_METADATA_SHOULD_NOT_APPEAR" not in prompt


def test_pydantic_ai_interpreter_episode_packet_prompt_excludes_sibling_episodes() -> None:
    first_ref = source_ref("ar1:ep0:act0:entries1")
    second_ref = replace(
        source_ref("ar1:ep1:act0:entries2"),
        episode_id=21,
        episode_ordinal=1,
        activity_unit_id=11,
    )
    first_activity = replace(activity_packet(first_ref), activity_text="EPISODE_ZERO_ONLY")
    second_activity = replace(
        activity_packet(second_ref),
        episode_id=21,
        episode_ordinal=1,
        activity_unit_id=11,
        activity_text="EPISODE_ONE_ONLY",
    )
    base_packet = packet(first_ref)
    first_episode = replace(
        base_packet.episode_packets[0],
        included_activities=(first_activity,),
        source_refs=(first_ref,),
    )
    second_episode = replace(
        base_packet.episode_packets[0],
        episode_id=21,
        manifest_id=22,
        ordinal=1,
        included_activities=(second_activity,),
        source_refs=(second_ref,),
    )
    source_packet = replace(
        base_packet,
        readiness=replace(base_packet.readiness, activity_count=2, episode_count=2, manifest_count=2),
        episode_packets=(first_episode, second_episode),
    )
    episode_packet = build_episode_interpretation_packet(source_packet, first_episode)
    output = interpretation_output(episode_packet, first_ref.source_ref_id)
    agent = FakePydanticAgent(output=output)
    interpreter = PydanticAISessionInterpreter(
        "test-provider:test-model",
        agent_factory=FakePydanticAgentFactory(agent),
    )

    interpreter.interpret(episode_packet)

    prompt = agent.prompts[0]
    assert "EPISODE_ZERO_ONLY" in prompt
    assert "EPISODE_ONE_ONLY" not in prompt
    assert '"episode_count":1' in prompt
    assert '"episodes":[{"activities"' in prompt


def test_pydantic_ai_interpreter_readiness_guard_runs_before_model_call() -> None:
    source_packet = packet(source_ref("local-ref"))
    not_ready = replace(
        source_packet,
        readiness=replace(
            source_packet.readiness,
            is_ready=False,
            blocked_reason="phase_5a_not_ready",
        ),
    )
    agent = FakePydanticAgent(output=interpretation_output(source_packet, "local-ref"))
    interpreter = PydanticAISessionInterpreter(
        "test-provider:test-model",
        agent_factory=FakePydanticAgentFactory(agent),
    )

    with pytest.raises(InterpreterUnavailableError, match="phase_5a_not_ready"):
        interpreter.interpret(not_ready)

    assert agent.prompts == []


def test_pydantic_ai_interpreter_no_claim_sources_guard_runs_before_model_call() -> None:
    source_packet = packet(source_ref("inherited-ref", source_origin=SOURCE_ORIGIN_INHERITED))
    agent = FakePydanticAgent(output=interpretation_output(source_packet, "inherited-ref"))
    interpreter = PydanticAISessionInterpreter(
        "test-provider:test-model",
        agent_factory=FakePydanticAgentFactory(agent),
    )

    with pytest.raises(InterpreterUnavailableError, match="no local or mixed claim-source"):
        interpreter.interpret(source_packet)

    assert agent.prompts == []


def test_pydantic_ai_interpreter_wraps_provider_failures_without_leaking_details() -> None:
    agent = FakePydanticAgent(error=RuntimeError("SECRET_PROMPT source excerpt API_KEY=abc123"))
    interpreter = PydanticAISessionInterpreter(
        "test-provider:test-model",
        agent_factory=FakePydanticAgentFactory(agent),
    )

    with pytest.raises(PydanticAIInterpreterError) as exc_info:
        interpreter.interpret(packet(source_ref("local-ref")))

    assert not isinstance(exc_info.value, InterpreterUnavailableError)
    message = str(exc_info.value)
    assert "PydanticAI session interpretation failed" == message
    assert "SECRET_PROMPT" not in message
    assert "source excerpt" not in message
    assert "API_KEY" not in message


def test_pydantic_ai_tool_summarizer_wraps_provider_failures_without_leaking_details() -> None:
    agent = FakePydanticAgent(error=RuntimeError("SECRET_TOOL_OUTPUT API_KEY=abc123"))
    summarizer = PydanticAIToolActivitySummarizer(
        "test-provider:test-model",
        agent_factory=FakePydanticAgentFactory(agent),
    )

    with pytest.raises(PydanticAIToolSummaryError) as exc_info:
        summarizer.summarize(tool_summary_input())

    message = str(exc_info.value)
    assert "PydanticAI tool activity summarization failed" == message
    assert "SECRET_TOOL_OUTPUT" not in message
    assert "API_KEY" not in message
