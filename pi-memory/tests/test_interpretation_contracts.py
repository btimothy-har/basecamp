from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest
from pi_memory.db import (
    SOURCE_ORIGIN_INHERITED,
    SOURCE_ORIGIN_LOCAL,
    SOURCE_ORIGIN_MIXED,
    SOURCE_ORIGIN_UNKNOWN,
)
from pi_memory.interpretation import (
    BoundedText,
    EpisodePacket,
    InterpretationOutput,
    InterpretationPacket,
    InterpretationReadiness,
    SourceRef,
    validate_interpretation_output,
)
from pi_memory.interpretation.contracts import InterpretationValidationError


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


def packet(*source_refs: SourceRef, analyzed_through_byte_offset: int = 456) -> InterpretationPacket:
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
            analyzed_through_byte_offset=analyzed_through_byte_offset,
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
                omitted_ranges=(),
                origin_counts={},
                claim_source_activity_count=len(source_refs),
                tool_result_text_byte_count=0,
                included_activities=(),
                source_refs=source_refs,
            ),
        ),
    )


def output(*source_ref_ids: str, **overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "analysis_run_id": 123,
        "analyzed_through_entry_id": 99,
        "analyzed_through_byte_offset": 456,
        "goal": "Summarize the session",
        "summary": "The session made a decision.",
        "claims": [
            {
                "source_ref_ids": list(source_ref_ids or ("local-ref",)),
                "kind": "decision",
                "statement": "Use the local implementation pattern.",
                "confidence": 0.8,
            },
        ],
        "open_questions": [],
        "citations": [{"source_ref_id": source_ref_ids[0] if source_ref_ids else "local-ref", "usage": "summary"}],
    }
    value.update(overrides)
    return value


def assert_invalid(candidate: Mapping[str, Any] | InterpretationOutput, source_packet: InterpretationPacket) -> None:
    with pytest.raises(InterpretationValidationError):
        validate_interpretation_output(candidate, source_packet)


def test_valid_output_passes_and_produces_safe_json() -> None:
    source_packet = packet(source_ref("local-ref"))

    validated = validate_interpretation_output(output("local-ref"), source_packet)

    assert validated.output.summary == "The session made a decision."
    assert validated.interpretation_json["analysis_run_id"] == 123
    assert validated.interpretation_json["claims"][0]["confidence"] == 0.8
    assert validated.citations_json == [
        {
            "usage": "claim",
            "claim_index": 0,
            "claim_kind": "decision",
            "source_ref_id": "local-ref",
            "activity_unit_id": 10,
            "episode_id": 20,
            "episode_ordinal": 0,
            "activity_index": 1,
            "activity_kind": "message",
            "source_origin": SOURCE_ORIGIN_LOCAL,
            "claim_source_allowed": True,
            "source_entry_row_ids": [30],
            "byte_start": 40,
            "byte_end": 50,
        },
        {
            "usage": "summary",
            "source_ref_id": "local-ref",
            "activity_unit_id": 10,
            "episode_id": 20,
            "episode_ordinal": 0,
            "activity_index": 1,
            "activity_kind": "message",
            "source_origin": SOURCE_ORIGIN_LOCAL,
            "claim_source_allowed": True,
            "source_entry_row_ids": [30],
            "byte_start": 40,
            "byte_end": 50,
        },
    ]


def test_pydantic_model_output_is_accepted() -> None:
    source_packet = packet(source_ref("local-ref"))
    model = InterpretationOutput.model_validate(output("local-ref"))

    validated = validate_interpretation_output(model, source_packet)

    assert validated.output is model


def test_none_goal_is_excluded_from_interpretation_json() -> None:
    source_packet = packet(source_ref("local-ref"))

    validated = validate_interpretation_output(output("local-ref", goal=None), source_packet)

    assert "goal" not in validated.interpretation_json


@pytest.mark.parametrize(
    "candidate",
    [
        {"claims": [{"source_ref_ids": [], "kind": "decision", "statement": "x", "confidence": 0.5}]},
        {"claims": [{"source_ref_ids": ["local-ref"], "kind": "invalid", "statement": "x", "confidence": 0.5}]},
        {"claims": [{"source_ref_ids": ["local-ref"], "kind": "decision", "statement": " ", "confidence": 0.5}]},
        {"claims": [{"source_ref_ids": ["local-ref"], "kind": "decision", "statement": "x", "confidence": 2.0}]},
        {"citations": [{"source_ref_id": "local-ref", "usage": "invalid"}]},
        {"summary": " "},
        {"analyzed_through_byte_offset": -1},
        {"unexpected": True},
    ],
)
def test_malformed_output_fails(candidate: dict[str, Any]) -> None:
    source_packet = packet(source_ref("local-ref"))

    assert_invalid(output("local-ref", **candidate), source_packet)


def test_missing_claim_source_ref_fails() -> None:
    source_packet = packet(source_ref("local-ref"))

    assert_invalid(output("missing-ref"), source_packet)


def test_missing_open_question_source_ref_fails() -> None:
    source_packet = packet(source_ref("local-ref"))
    candidate = output(
        "local-ref",
        open_questions=[{"question": "What happened?", "source_ref_ids": ["missing-ref"]}],
    )

    assert_invalid(candidate, source_packet)


def test_missing_standalone_citation_source_ref_fails() -> None:
    source_packet = packet(source_ref("local-ref"))
    candidate = output("local-ref", citations=[{"source_ref_id": "missing-ref", "usage": "summary"}])

    assert_invalid(candidate, source_packet)


def test_non_interpretable_packet_fails() -> None:
    source_packet = packet(source_ref("local-ref"))
    not_ready = replace(
        source_packet,
        readiness=replace(
            source_packet.readiness,
            is_ready=False,
            blocked_reason="phase_5a_not_ready",
        ),
    )

    assert_invalid(output("local-ref"), not_ready)


def test_no_claim_source_packet_fails() -> None:
    source_packet = packet(source_ref("local-ref"))
    no_claim_sources = replace(
        source_packet,
        readiness=replace(source_packet.readiness, claim_source_activity_count=0),
    )

    assert_invalid(output("local-ref"), no_claim_sources)


def test_stale_packet_fails() -> None:
    source_packet = packet(source_ref("local-ref"))
    stale = replace(
        source_packet,
        readiness=replace(source_packet.readiness, is_stale=True),
    )

    assert_invalid(output("local-ref"), stale)


def test_inherited_only_claim_fails() -> None:
    source_packet = packet(
        source_ref("inherited-ref", source_origin=SOURCE_ORIGIN_INHERITED, claim_source_allowed=True),
    )

    assert_invalid(output("inherited-ref"), source_packet)


def test_unknown_origin_claim_fails() -> None:
    source_packet = packet(source_ref("unknown-ref", source_origin=SOURCE_ORIGIN_UNKNOWN, claim_source_allowed=True))

    assert_invalid(output("unknown-ref"), source_packet)


def test_local_origin_without_claim_source_flag_fails() -> None:
    source_packet = packet(source_ref("local-ref", source_origin=SOURCE_ORIGIN_LOCAL, claim_source_allowed=False))

    assert_invalid(output("local-ref"), source_packet)


def test_claim_with_inherited_and_mixed_support_passes() -> None:
    source_packet = packet(
        source_ref("inherited-ref", source_origin=SOURCE_ORIGIN_INHERITED, claim_source_allowed=True),
        source_ref("mixed-ref", source_origin=SOURCE_ORIGIN_MIXED, claim_source_allowed=True),
    )

    validated = validate_interpretation_output(output("inherited-ref", "mixed-ref"), source_packet)

    assert [citation["source_ref_id"] for citation in validated.citations_json[:2]] == ["inherited-ref", "mixed-ref"]


def test_claim_with_only_mixed_support_passes() -> None:
    source_packet = packet(source_ref("mixed-ref", source_origin=SOURCE_ORIGIN_MIXED, claim_source_allowed=True))

    validated = validate_interpretation_output(output("mixed-ref"), source_packet)

    assert validated.output.claims[0].source_ref_ids == ["mixed-ref"]


def test_analysis_run_id_mismatch_fails() -> None:
    source_packet = packet(source_ref("local-ref"))

    assert_invalid(output("local-ref", analysis_run_id=999), source_packet)


def test_analyzed_through_entry_id_mismatch_fails() -> None:
    source_packet = packet(source_ref("local-ref"))

    assert_invalid(output("local-ref", analyzed_through_entry_id=100), source_packet)


def test_analyzed_through_byte_offset_mismatch_fails() -> None:
    source_packet = packet(source_ref("local-ref"), analyzed_through_byte_offset=789)

    assert_invalid(output("local-ref"), source_packet)


def test_open_question_citing_inherited_source_is_allowed() -> None:
    source_packet = packet(
        source_ref("local-ref"),
        source_ref("inherited-ref", source_origin=SOURCE_ORIGIN_INHERITED, claim_source_allowed=False),
    )
    candidate = output(
        "local-ref",
        open_questions=[
            {"question": "Should the inherited behavior be preserved?", "source_ref_ids": ["inherited-ref"]},
        ],
    )

    validated = validate_interpretation_output(candidate, source_packet)

    assert validated.output.open_questions[0].source_ref_ids == ["inherited-ref"]
    assert any(
        citation["usage"] == "open_question" and citation["source_ref_id"] == "inherited-ref"
        for citation in validated.citations_json
    )
