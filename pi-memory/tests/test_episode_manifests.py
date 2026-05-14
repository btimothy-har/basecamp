from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from pi_memory.analysis import (
    MANIFEST_HEAD_ACTIVITIES,
    MANIFEST_TAIL_ACTIVITIES,
    MAX_MANIFEST_ACTIVITIES,
    NormalizedActivity,
    NormalizedEpisode,
    build_episode_manifest,
    build_episode_manifests,
    build_session_snapshot_shell,
)
from pi_memory.db import (
    ACTIVITY_KIND_TOOL_PAIR,
    ACTIVITY_KIND_USER_TEXT,
    EPISODE_CLOSE_REASON_CURRENT_CURSOR,
    EPISODE_CLOSE_REASON_TIME_GAP,
    EPISODE_STATUS_CLOSED,
    EPISODE_STATUS_OPEN,
    SESSION_SNAPSHOT_STATUS_READY_FOR_INTERPRETATION,
)

BASE_TIME = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)


def activity(
    sequence: int,
    kind: str = ACTIVITY_KIND_USER_TEXT,
    *,
    row_ids: tuple[int, ...] | None = None,
    byte_start: int | None = None,
    byte_end: int | None = None,
    timestamp_start: datetime | None = None,
    timestamp_end: datetime | None = None,
    result_text_byte_count: int = 0,
    result_text_line_count: int = 0,
    receipt_json: dict[str, Any] | None = None,
    source_metadata_json: dict[str, Any] | None = None,
) -> NormalizedActivity:
    start = sequence * 100 if byte_start is None else byte_start
    end = start + 50 if byte_end is None else byte_end
    timestamp = BASE_TIME + timedelta(seconds=sequence)
    return NormalizedActivity(
        kind=kind,
        source_entry_ids=(sequence,) if row_ids is None else row_ids,
        byte_start=start,
        byte_end=end,
        timestamp_start=timestamp if timestamp_start is None else timestamp_start,
        timestamp_end=timestamp if timestamp_end is None else timestamp_end,
        message_role="toolResult" if kind == ACTIVITY_KIND_TOOL_PAIR else "user",
        tool_call_id="call-1" if kind == ACTIVITY_KIND_TOOL_PAIR else None,
        tool_name="bash" if kind == ACTIVITY_KIND_TOOL_PAIR else None,
        is_error=False if kind == ACTIVITY_KIND_TOOL_PAIR else None,
        raw_text_available=True,
        text_char_count=4 if kind == ACTIVITY_KIND_USER_TEXT else 0,
        result_text_byte_count=result_text_byte_count,
        result_text_line_count=result_text_line_count,
        receipt_json=receipt_json or {},
        source_metadata_json=source_metadata_json or {},
        sequence=sequence,
    )


def episode(
    activities: list[NormalizedActivity],
    *,
    ordinal: int = 0,
    status: str = EPISODE_STATUS_OPEN,
    close_reason: str = EPISODE_CLOSE_REASON_CURRENT_CURSOR,
    boundary_metadata: dict[str, Any] | None = None,
) -> NormalizedEpisode:
    return NormalizedEpisode(
        ordinal=ordinal,
        status=status,
        close_reason=close_reason,
        activities=tuple(activities),
        first_entry_id=next(
            (item.source_entry_ids[0] for item in activities if item.source_entry_ids),
            None,
        ),
        last_entry_id=next(
            (item.source_entry_ids[-1] for item in reversed(activities) if item.source_entry_ids),
            None,
        ),
        byte_start=min((item.byte_start for item in activities), default=0),
        byte_end=max((item.byte_end for item in activities), default=0),
        timestamp_start=min(
            timestamp
            for item in activities
            for timestamp in (item.timestamp_start, item.timestamp_end)
            if timestamp is not None
        )
        if activities
        else None,
        timestamp_end=max(
            timestamp
            for item in activities
            for timestamp in (item.timestamp_start, item.timestamp_end)
            if timestamp is not None
        )
        if activities
        else None,
        activity_count=len(activities),
        message_count=sum(1 for item in activities if item.kind == ACTIVITY_KIND_USER_TEXT),
        tool_pair_count=sum(1 for item in activities if item.kind == ACTIVITY_KIND_TOOL_PAIR),
        boundary_metadata=boundary_metadata or {},
    )


def test_basic_manifest_includes_metadata_activity_map_spans_and_tool_receipt() -> None:
    tool = activity(
        2,
        ACTIVITY_KIND_TOOL_PAIR,
        row_ids=(2, 3),
        result_text_byte_count=120,
        result_text_line_count=6,
        receipt_json={
            "tool_call_id": "call-1",
            "tool_name": "bash",
            "argument_keys": ["command"],
            "result_status": "success",
        },
        source_metadata_json={"call_content_index": 1, "result_entry_id": "entry-3"},
    )
    built = build_episode_manifest(
        episode(
            [activity(1), tool],
            boundary_metadata={"gap_seconds": 3600.0},
        ),
    )

    assert built.episode_ordinal == 0
    assert built.activity_count == 2
    assert built.tool_pair_count == 1
    assert built.first_entry_id == 1
    assert built.last_entry_id == 3
    assert built.byte_start == 100
    assert built.byte_end == 250
    assert built.omitted_raw_text_bytes == 120

    activity_map = built.activity_map_json
    assert activity_map["episode"]["ordinal"] == 0
    assert activity_map["episode"]["status"] == EPISODE_STATUS_OPEN
    assert activity_map["episode"]["close_reason"] == EPISODE_CLOSE_REASON_CURRENT_CURSOR
    assert activity_map["episode"]["timestamp_start"] == (BASE_TIME + timedelta(seconds=1)).isoformat()
    assert activity_map["episode"]["boundary_metadata"] == {"gap_seconds": 3600.0}
    assert activity_map["included_activity_count"] == 2
    assert activity_map["omitted_activity_count"] == 0

    tool_map = activity_map["activities"][1]
    assert tool_map["index"] == 1
    assert tool_map["sequence"] == 2
    assert tool_map["kind"] == ACTIVITY_KIND_TOOL_PAIR
    assert tool_map["source_entry_ids"] == [2, 3]
    assert tool_map["tool_call_id"] == "call-1"
    assert tool_map["tool_name"] == "bash"
    assert tool_map["receipt_json"]["argument_keys"] == ["command"]
    assert tool_map["source_metadata_json"]["call_content_index"] == 1

    assert built.source_spans_json[0]["kind"] == "episode"
    assert [span["kind"] for span in built.source_spans_json] == [
        "episode",
        "activity",
        "activity",
    ]
    assert built.source_spans_json[2]["source_entry_ids"] == [2, 3]


def test_manifest_omits_large_raw_tool_output_from_receipt_details() -> None:
    raw_output = "RAW_TOOL_OUTPUT_SENTINEL\n" * 1_000
    tool = activity(
        1,
        ACTIVITY_KIND_TOOL_PAIR,
        result_text_byte_count=len(raw_output.encode("utf-8")),
        result_text_line_count=1_000,
        receipt_json={"details": {"stdout": raw_output}},
    )

    built = build_episode_manifest(episode([tool]))
    serialized = json.dumps(built.activity_map_json, sort_keys=True)

    assert "RAW_TOOL_OUTPUT_SENTINEL" not in serialized
    details = built.activity_map_json["activities"][0]["receipt_json"]["details"]
    assert details["stdout"] == {
        "omitted": True,
        "char_count": len(raw_output),
        "byte_count": len(raw_output.encode("utf-8")),
    }
    assert built.omitted_raw_text_bytes == len(raw_output.encode("utf-8"))


def test_large_episode_activity_map_is_bounded_to_head_and_tail_ranges() -> None:
    count = MAX_MANIFEST_ACTIVITIES + 5
    built = build_episode_manifest(episode([activity(index) for index in range(count)]))

    activity_map = built.activity_map_json
    assert len(activity_map["activities"]) == MAX_MANIFEST_ACTIVITIES
    assert activity_map["included_activity_count"] == MAX_MANIFEST_ACTIVITIES
    assert activity_map["omitted_activity_count"] == 5
    assert activity_map["included_ranges"] == [
        {"start_index": 0, "end_index": MANIFEST_HEAD_ACTIVITIES - 1, "count": MANIFEST_HEAD_ACTIVITIES},
        {
            "start_index": count - MANIFEST_TAIL_ACTIVITIES,
            "end_index": count - 1,
            "count": MANIFEST_TAIL_ACTIVITIES,
        },
    ]
    assert activity_map["omitted_ranges"] == [
        {
            "start_index": MANIFEST_HEAD_ACTIVITIES,
            "end_index": count - MANIFEST_TAIL_ACTIVITIES - 1,
            "count": 5,
        },
    ]
    assert [item["index"] for item in activity_map["activities"][:3]] == [0, 1, 2]
    assert [item["index"] for item in activity_map["activities"][-3:]] == [102, 103, 104]
    assert len(built.source_spans_json) == MAX_MANIFEST_ACTIVITIES + 1


def test_snapshot_shell_from_multiple_episodes_has_counts_and_no_semantic_fields() -> None:
    first = episode(
        [activity(1), activity(2, ACTIVITY_KIND_TOOL_PAIR, row_ids=(2, 3))],
        ordinal=0,
        status=EPISODE_STATUS_CLOSED,
        close_reason=EPISODE_CLOSE_REASON_TIME_GAP,
    )
    second = episode([activity(4)], ordinal=1)
    manifests = build_episode_manifests([first, second])

    shell = build_session_snapshot_shell([first, second], manifests)

    assert shell.status == SESSION_SNAPSHOT_STATUS_READY_FOR_INTERPRETATION
    assert shell.analyzed_through_entry_id == 4
    assert shell.analyzed_through_byte_offset == second.byte_end
    assert shell.activity_count == 3
    assert shell.episode_count == 2
    assert shell.manifest_count == 2
    assert shell.tool_pair_count == 1
    assert shell.snapshot_json["ready_for_interpretation"] is True
    assert shell.snapshot_json["counts"] == {
        "activity_count": 3,
        "episode_count": 2,
        "manifest_count": 2,
        "tool_pair_count": 1,
    }
    assert shell.snapshot_json["episodes"] == [
        {
            "ordinal": 0,
            "status": EPISODE_STATUS_CLOSED,
            "close_reason": EPISODE_CLOSE_REASON_TIME_GAP,
        },
        {
            "ordinal": 1,
            "status": EPISODE_STATUS_OPEN,
            "close_reason": EPISODE_CLOSE_REASON_CURRENT_CURSOR,
        },
    ]
    serialized = json.dumps(shell.snapshot_json, sort_keys=True)
    assert "summary" not in serialized
    assert "goal" not in serialized
    assert "candidates" not in serialized


def test_empty_snapshot_input_returns_zero_ready_shell() -> None:
    shell = build_session_snapshot_shell([], [])

    assert shell.status == SESSION_SNAPSHOT_STATUS_READY_FOR_INTERPRETATION
    assert shell.analyzed_through_entry_id is None
    assert shell.analyzed_through_byte_offset == 0
    assert shell.activity_count == 0
    assert shell.episode_count == 0
    assert shell.manifest_count == 0
    assert shell.tool_pair_count == 0
    assert shell.snapshot_json["ready_for_interpretation"] is True
    assert shell.snapshot_json["counts"] == {
        "activity_count": 0,
        "episode_count": 0,
        "manifest_count": 0,
        "tool_pair_count": 0,
    }
    assert shell.snapshot_json["analyzed_through"] == {
        "entry_id": None,
        "byte_offset": 0,
    }
    assert shell.snapshot_json["episodes"] == []
