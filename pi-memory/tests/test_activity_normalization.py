from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from pi_memory.analysis import normalize_transcript_entries
from pi_memory.db import (
    ACTIVITY_KIND_ASSISTANT_TEXT,
    ACTIVITY_KIND_ASSISTANT_THINKING,
    ACTIVITY_KIND_COMPACTION,
    ACTIVITY_KIND_CUSTOM_EVENT,
    ACTIVITY_KIND_ORPHAN_TOOL_RESULT,
    ACTIVITY_KIND_PENDING_TOOL_CALL,
    ACTIVITY_KIND_SESSION_EVENT,
    ACTIVITY_KIND_TOOL_PAIR,
    ACTIVITY_KIND_USER_TEXT,
    SOURCE_ORIGIN_INHERITED,
    SOURCE_ORIGIN_LOCAL,
    SOURCE_ORIGIN_MIXED,
    SOURCE_ORIGIN_UNKNOWN,
    TranscriptEntry,
)

BASE_TIME = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)


def entry(
    row_id: int,
    payload: dict[str, Any] | str,
    *,
    byte_start: int | None = None,
    entry_type: str | None = None,
    message_role: str | None = None,
) -> TranscriptEntry:
    raw_line = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
    start = row_id * 100 if byte_start is None else byte_start
    parsed_type = payload.get("type") if isinstance(payload, dict) else None
    parsed_role = payload.get("message", {}).get("role") if isinstance(payload, dict) else None
    return TranscriptEntry(
        id=row_id,
        transcript_id=1,
        entry_id=f"entry-{row_id}",
        parent_id=None,
        entry_type=entry_type or parsed_type or "message",
        message_role=message_role if message_role is not None else parsed_role,
        timestamp=BASE_TIME + timedelta(seconds=row_id),
        raw_line=raw_line,
        byte_start=start,
        byte_end=start + len(raw_line.encode("utf-8")),
    )


def message_entry(
    row_id: int,
    role: str,
    content: Any = None,
    *,
    byte_start: int | None = None,
    **extra: Any,
) -> TranscriptEntry:
    message = {"role": role, **extra}
    if content is not None:
        message["content"] = content
    return entry(
        row_id,
        {"type": "message", "id": f"entry-{row_id}", "message": message},
        byte_start=byte_start,
    )


def test_normalizes_user_text_assistant_text_and_thinking() -> None:
    entries = [
        message_entry(1, "user", "hello world"),
        message_entry(
            2,
            "assistant",
            [
                {"type": "thinking", "thinking": "considering"},
                {"type": "text", "text": "answer"},
            ],
        ),
    ]

    activities = normalize_transcript_entries(entries)

    assert [activity.kind for activity in activities] == [
        ACTIVITY_KIND_USER_TEXT,
        ACTIVITY_KIND_ASSISTANT_THINKING,
        ACTIVITY_KIND_ASSISTANT_TEXT,
    ]
    assert [activity.text_char_count for activity in activities] == [11, 11, 6]
    assert [activity.message_role for activity in activities] == ["user", "assistant", "assistant"]
    assert [activity.source_entry_ids for activity in activities] == [(1,), (2,), (2,)]


def test_pairs_multiple_tool_calls_with_results_in_call_order_and_spans() -> None:
    assistant = message_entry(
        1,
        "assistant",
        [
            {"type": "text", "text": "I will call tools"},
            {"type": "toolCall", "id": "call-1", "name": "read", "arguments": {"path": "a.txt"}},
            {"type": "toolCall", "id": "call-2", "name": "grep", "arguments": {"pattern": "needle"}},
        ],
        byte_start=100,
    )
    result_one = message_entry(
        2,
        "toolResult",
        [{"type": "text", "text": "first\nresult"}],
        byte_start=1_000,
        toolCallId="call-1",
        isError=False,
    )
    result_two = message_entry(
        3,
        "toolResult",
        [{"type": "text", "text": "second"}],
        byte_start=2_000,
        toolCallId="call-2",
        isError=True,
    )

    activities = normalize_transcript_entries([result_two, assistant, result_one])

    assert [activity.kind for activity in activities] == [
        ACTIVITY_KIND_ASSISTANT_TEXT,
        ACTIVITY_KIND_TOOL_PAIR,
        ACTIVITY_KIND_TOOL_PAIR,
    ]
    first_pair, second_pair = activities[1], activities[2]
    assert [first_pair.tool_call_id, second_pair.tool_call_id] == ["call-1", "call-2"]
    assert [first_pair.tool_name, second_pair.tool_name] == ["read", "grep"]
    assert first_pair.source_entry_ids == (1, 2)
    assert second_pair.source_entry_ids == (1, 3)
    assert first_pair.byte_start == assistant.byte_start
    assert first_pair.byte_end == result_one.byte_end
    assert first_pair.result_text_byte_count == len(b"first\nresult")
    assert first_pair.result_text_line_count == 2
    assert second_pair.is_error is True
    assert first_pair.receipt_json["argument_keys"] == ["path"]
    assert second_pair.receipt_json["argument_keys"] == ["pattern"]
    assert first_pair.source_metadata_json["call_content_index"] == 1
    assert first_pair.sequence < second_pair.sequence


def test_tool_pair_uses_result_tool_name_when_call_name_is_missing() -> None:
    assistant = message_entry(
        1,
        "assistant",
        [{"type": "toolCall", "id": "call-1", "arguments": {"command": "pwd"}}],
    )
    result = message_entry(
        2,
        "toolResult",
        "ok",
        toolCallId="call-1",
        toolName="bash",
    )

    activities = normalize_transcript_entries([assistant, result])

    assert len(activities) == 1
    assert activities[0].kind == ACTIVITY_KIND_TOOL_PAIR
    assert activities[0].tool_name == "bash"
    assert activities[0].receipt_json["tool_name"] == "bash"


def test_orphan_tool_result_without_matching_call() -> None:
    tool_result = message_entry(
        1,
        "toolResult",
        "orphan output",
        toolCallId="missing-call",
        toolName="bash",
        status="success",
    )

    activities = normalize_transcript_entries([tool_result])

    assert len(activities) == 1
    activity = activities[0]
    assert activity.kind == ACTIVITY_KIND_ORPHAN_TOOL_RESULT
    assert activity.tool_call_id == "missing-call"
    assert activity.tool_name == "bash"
    assert activity.is_error is False
    assert activity.result_text_byte_count == len(b"orphan output")
    assert activity.result_text_line_count == 1
    assert activity.receipt_json["result_status"] == "success"


def test_pending_tool_call_is_emitted_at_eof() -> None:
    assistant = message_entry(
        1,
        "assistant",
        [
            {"type": "text", "text": "before"},
            {"type": "toolCall", "id": "call-1", "name": "read", "arguments": {"path": "x"}},
        ],
    )

    activities = normalize_transcript_entries([assistant])

    assert [activity.kind for activity in activities] == [
        ACTIVITY_KIND_ASSISTANT_TEXT,
        ACTIVITY_KIND_PENDING_TOOL_CALL,
    ]
    pending = activities[1]
    assert pending.tool_call_id == "call-1"
    assert pending.tool_name == "read"
    assert pending.source_entry_ids == (1,)
    assert pending.receipt_json["argument_keys"] == ["path"]


def test_anonymous_pending_tool_call_is_emitted_at_eof() -> None:
    assistant = message_entry(
        1,
        "assistant",
        [{"type": "toolCall", "name": "anonymous", "arguments": {"path": "x"}}],
    )

    activities = normalize_transcript_entries([assistant])

    assert len(activities) == 1
    assert activities[0].kind == ACTIVITY_KIND_PENDING_TOOL_CALL
    assert activities[0].tool_call_id is None
    assert activities[0].tool_name == "anonymous"


def test_compaction_metadata_extracts_bounded_fields() -> None:
    summary = "summary " * 400
    compaction = entry(
        1,
        {
            "type": "compaction",
            "id": "entry-1",
            "summary": summary,
            "firstKeptEntryId": "entry-20",
            "tokensBefore": 12345,
            "details": {"large": "x" * 5000, "small": True},
        },
    )

    activities = normalize_transcript_entries([compaction])

    assert len(activities) == 1
    activity = activities[0]
    assert activity.kind == ACTIVITY_KIND_COMPACTION
    assert activity.source_metadata_json["firstKeptEntryId"] == "entry-20"
    assert activity.source_metadata_json["tokensBefore"] == 12345
    assert activity.source_metadata_json["details_keys"] == ["large", "small"]
    assert activity.source_metadata_json["summary"]["is_truncated"] is True
    assert activity.source_metadata_json["summary"]["char_count"] == len(summary)
    assert len(activity.source_metadata_json["summary"]["preview"]) == 1_200


def test_session_entry_becomes_session_event() -> None:
    session_entry = entry(1, {"type": "session", "id": "entry-1", "cwd": "/workspace"})

    activities = normalize_transcript_entries([session_entry])

    assert len(activities) == 1
    assert activities[0].kind == ACTIVITY_KIND_SESSION_EVENT
    assert activities[0].source_metadata_json["entry_type"] == "session"


def test_malformed_json_becomes_custom_event() -> None:
    malformed = entry(1, '{"type":"message",', entry_type="message", message_role=None)

    activities = normalize_transcript_entries([malformed])

    assert len(activities) == 1
    activity = activities[0]
    assert activity.kind == ACTIVITY_KIND_CUSTOM_EVENT
    assert activity.source_metadata_json["parse_issue"] == "malformed_json"


def test_non_object_json_becomes_custom_event() -> None:
    non_object = entry(1, '["not", "an", "object"]', entry_type="custom", message_role=None)

    activities = normalize_transcript_entries([non_object])

    assert len(activities) == 1
    assert activities[0].kind == ACTIVITY_KIND_CUSTOM_EVENT
    assert activities[0].source_metadata_json["parse_issue"] == "non_object_json"


def test_input_entries_are_sorted_deterministically_by_byte_start_then_id() -> None:
    later = message_entry(2, "user", "later")
    earlier_higher_id = message_entry(5, "user", "second", byte_start=100)
    earlier_lower_id = message_entry(1, "user", "first", byte_start=100)

    activities = normalize_transcript_entries([later, earlier_higher_id, earlier_lower_id])

    assert [activity.source_entry_ids for activity in activities] == [(1,), (5,), (2,)]
    assert [activity.text_char_count for activity in activities] == [5, 6, 5]


def test_source_origins_aggregate_and_partition_source_entries() -> None:
    local_user = message_entry(1, "user", "local")
    inherited_user = message_entry(2, "user", "inherited")
    unknown_user = message_entry(3, "user", "unknown")
    no_id_user = message_entry(4, "user", "no id")
    no_id_user.id = None
    assistant = message_entry(
        5,
        "assistant",
        [{"type": "toolCall", "id": "call-1", "name": "bash", "arguments": {"cmd": "pwd"}}],
    )
    result = message_entry(6, "toolResult", "ok", toolCallId="call-1")

    activities = normalize_transcript_entries(
        [local_user, inherited_user, unknown_user, no_id_user, assistant, result],
        entry_source_origins={
            1: SOURCE_ORIGIN_LOCAL,
            2: SOURCE_ORIGIN_INHERITED,
            3: SOURCE_ORIGIN_UNKNOWN,
            5: SOURCE_ORIGIN_INHERITED,
            6: SOURCE_ORIGIN_LOCAL,
        },
    )

    assert [activity.source_origin for activity in activities] == [
        SOURCE_ORIGIN_LOCAL,
        SOURCE_ORIGIN_INHERITED,
        SOURCE_ORIGIN_UNKNOWN,
        SOURCE_ORIGIN_UNKNOWN,
        SOURCE_ORIGIN_MIXED,
    ]
    assert activities[0].source_metadata_json["source_entry_ids_by_origin"] == {SOURCE_ORIGIN_LOCAL: [1]}
    assert activities[1].source_metadata_json["source_entry_ids_by_origin"] == {SOURCE_ORIGIN_INHERITED: [2]}
    assert activities[2].source_metadata_json["source_entry_ids_by_origin"] == {SOURCE_ORIGIN_UNKNOWN: [3]}
    assert activities[3].source_metadata_json["source_entry_ids_by_origin"] == {SOURCE_ORIGIN_UNKNOWN: []}
    assert activities[4].source_metadata_json["source_entry_ids_by_origin"] == {
        SOURCE_ORIGIN_INHERITED: [5],
        SOURCE_ORIGIN_LOCAL: [6],
    }


def test_large_tool_result_receipt_has_counts_and_bounded_preview_without_full_output() -> None:
    large_output = "A" * 5_000
    assistant = message_entry(
        1,
        "assistant",
        [{"type": "toolCall", "id": "call-1", "name": "bash", "arguments": {"cmd": "generate"}}],
    )
    result = message_entry(
        2,
        "toolResult",
        [{"type": "text", "text": large_output}],
        toolCallId="call-1",
        details={"stdout": large_output, "exitCode": 0},
    )

    activities = normalize_transcript_entries([assistant, result])

    assert len(activities) == 1
    activity = activities[0]
    assert activity.kind == ACTIVITY_KIND_TOOL_PAIR
    assert activity.result_text_byte_count == 5_000
    assert activity.result_text_line_count == 1
    assert activity.receipt_json["result_text_byte_count"] == 5_000
    assert activity.receipt_json["result_text_line_count"] == 1
    assert activity.receipt_json["details"]["large_fields"]["stdout"] == {
        "byte_count": 5_000,
        "line_count": 1,
    }
    assert activity.receipt_json["details"]["scalars"]["exitCode"] == 0
    assert activity.receipt_json["arguments_preview"]["is_truncated"] is False
    receipt_json = json.dumps(activity.receipt_json, sort_keys=True)
    assert large_output not in receipt_json
    assert len(activity.receipt_json["arguments_preview"]["preview"]) < len(large_output)
