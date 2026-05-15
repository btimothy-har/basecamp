from __future__ import annotations

import socket
from dataclasses import replace

import pytest
from pi_memory.db import SOURCE_ORIGIN_INHERITED, SOURCE_ORIGIN_LOCAL, SOURCE_ORIGIN_MIXED
from pi_memory.interpretation import (
    DETERMINISTIC_INTERPRETER_MODE,
    DETERMINISTIC_INTERPRETER_MODEL,
    DETERMINISTIC_INTERPRETER_PROVIDER,
    INTERPRETATION_PROMPT_VERSION,
    INTERPRETATION_SCHEMA_VERSION,
    BoundedText,
    DeterministicSessionInterpreter,
    EpisodePacket,
    InterpretationOutput,
    InterpretationPacket,
    InterpretationReadiness,
    InterpretationResult,
    InterpreterUnavailableError,
    SessionInterpreter,
    SourceRef,
    validate_interpretation_output,
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


def interpret_with_protocol(
    interpreter: SessionInterpreter,
    source_packet: InterpretationPacket,
) -> InterpretationResult:
    return interpreter.interpret(source_packet)


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
    assert (
        result.output.analyzed_through_byte_offset
        == source_packet.readiness.analyzed_through_byte_offset
    )
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
