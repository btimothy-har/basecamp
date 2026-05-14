from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pi_memory.analysis import NormalizedActivity, segment_activities
from pi_memory.db import (
    ACTIVITY_KIND_ASSISTANT_TEXT,
    ACTIVITY_KIND_COMPACTION,
    ACTIVITY_KIND_CUSTOM_EVENT,
    ACTIVITY_KIND_SESSION_EVENT,
    ACTIVITY_KIND_TOOL_PAIR,
    ACTIVITY_KIND_USER_TEXT,
    EPISODE_CLOSE_REASON_COMPACTION,
    EPISODE_CLOSE_REASON_CURRENT_CURSOR,
    EPISODE_CLOSE_REASON_TIME_GAP,
    EPISODE_CLOSE_REASON_TRANSCRIPT_END,
    EPISODE_STATUS_CLOSED,
    EPISODE_STATUS_OPEN,
)

BASE_TIME = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)


def activity(
    row_id: int,
    kind: str = ACTIVITY_KIND_USER_TEXT,
    *,
    byte_start: int | None = None,
    byte_end: int | None = None,
    timestamp_start: datetime | None = None,
    timestamp_end: datetime | None = None,
    source_entry_ids: tuple[int, ...] | None = None,
    sequence: int | None = None,
    source_metadata_json: dict[str, Any] | None = None,
    result_text_byte_count: int = 0,
    result_text_line_count: int = 0,
) -> NormalizedActivity:
    start = row_id * 100 if byte_start is None else byte_start
    end = start + 10 if byte_end is None else byte_end
    timestamp = BASE_TIME + timedelta(seconds=row_id)
    return NormalizedActivity(
        kind=kind,
        source_entry_ids=(row_id,) if source_entry_ids is None else source_entry_ids,
        byte_start=start,
        byte_end=end,
        timestamp_start=timestamp if timestamp_start is None else timestamp_start,
        timestamp_end=timestamp if timestamp_end is None else timestamp_end,
        message_role="user" if kind == ACTIVITY_KIND_USER_TEXT else None,
        tool_call_id="call-1" if kind == ACTIVITY_KIND_TOOL_PAIR else None,
        tool_name="bash" if kind == ACTIVITY_KIND_TOOL_PAIR else None,
        is_error=False if kind == ACTIVITY_KIND_TOOL_PAIR else None,
        raw_text_available=True,
        text_char_count=4 if kind == ACTIVITY_KIND_USER_TEXT else 0,
        result_text_byte_count=result_text_byte_count,
        result_text_line_count=result_text_line_count,
        receipt_json={},
        source_metadata_json=source_metadata_json or {},
        sequence=row_id if sequence is None else sequence,
    )


def test_empty_input_returns_empty_list() -> None:
    assert segment_activities([]) == []


def test_no_boundary_returns_one_final_current_cursor_open_episode() -> None:
    episodes = segment_activities(
        [
            activity(1, ACTIVITY_KIND_USER_TEXT),
            activity(2, ACTIVITY_KIND_ASSISTANT_TEXT),
        ],
    )

    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.ordinal == 0
    assert episode.status == EPISODE_STATUS_OPEN
    assert episode.close_reason == EPISODE_CLOSE_REASON_CURRENT_CURSOR
    assert [item.source_entry_ids for item in episode.activities] == [(1,), (2,)]


def test_final_transcript_end_close_reason_returns_closed_episode() -> None:
    episodes = segment_activities(
        [activity(1)],
        final_close_reason=EPISODE_CLOSE_REASON_TRANSCRIPT_END,
    )

    assert len(episodes) == 1
    assert episodes[0].status == EPISODE_STATUS_CLOSED
    assert episodes[0].close_reason == EPISODE_CLOSE_REASON_TRANSCRIPT_END


def test_compaction_closes_episode_and_includes_compaction_metadata() -> None:
    compaction_metadata = {"entry_type": "compaction", "summary": {"preview": "done"}}
    compaction = activity(
        2,
        ACTIVITY_KIND_COMPACTION,
        source_metadata_json=compaction_metadata,
    )

    episodes = segment_activities([activity(1), compaction, activity(3)])

    assert len(episodes) == 2
    closing_episode = episodes[0]
    assert closing_episode.status == EPISODE_STATUS_CLOSED
    assert closing_episode.close_reason == EPISODE_CLOSE_REASON_COMPACTION
    assert [item.kind for item in closing_episode.activities] == [
        ACTIVITY_KIND_USER_TEXT,
        ACTIVITY_KIND_COMPACTION,
    ]
    assert closing_episode.boundary_metadata == {
        "source_entry_ids": (2,),
        "source_metadata_json": compaction_metadata,
    }
    assert episodes[1].status == EPISODE_STATUS_OPEN
    assert episodes[1].activities == (activity(3),)


def test_timestamp_gap_splits_episode_and_records_gap_seconds() -> None:
    first = activity(
        1,
        timestamp_start=BASE_TIME,
        timestamp_end=BASE_TIME + timedelta(minutes=5),
    )
    second = activity(
        2,
        timestamp_start=BASE_TIME + timedelta(hours=1, minutes=5),
        timestamp_end=BASE_TIME + timedelta(hours=1, minutes=6),
    )

    episodes = segment_activities([first, second])

    assert len(episodes) == 2
    assert episodes[0].status == EPISODE_STATUS_CLOSED
    assert episodes[0].close_reason == EPISODE_CLOSE_REASON_TIME_GAP
    assert episodes[0].boundary_metadata == {"gap_seconds": 3600.0}
    assert episodes[1].status == EPISODE_STATUS_OPEN
    assert episodes[1].activities == (second,)


def test_compaction_closes_previous_episode_even_after_timestamp_gap() -> None:
    first = activity(
        1,
        timestamp_start=BASE_TIME,
        timestamp_end=BASE_TIME + timedelta(minutes=5),
    )
    compaction = activity(
        2,
        ACTIVITY_KIND_COMPACTION,
        timestamp_start=BASE_TIME + timedelta(hours=3),
        timestamp_end=BASE_TIME + timedelta(hours=3),
    )

    episodes = segment_activities([first, compaction])

    assert len(episodes) == 1
    assert episodes[0].close_reason == EPISODE_CLOSE_REASON_COMPACTION
    assert [item.kind for item in episodes[0].activities] == [
        ACTIVITY_KIND_USER_TEXT,
        ACTIVITY_KIND_COMPACTION,
    ]


def test_large_raw_tool_output_metrics_do_not_split_episode() -> None:
    large_tool = activity(
        2,
        ACTIVITY_KIND_TOOL_PAIR,
        source_entry_ids=(2, 3),
        byte_end=1_000_000,
        result_text_byte_count=5_000_000,
        result_text_line_count=250_000,
    )

    episodes = segment_activities([activity(1), large_tool, activity(4)])

    assert len(episodes) == 1
    assert [item.kind for item in episodes[0].activities] == [
        ACTIVITY_KIND_USER_TEXT,
        ACTIVITY_KIND_TOOL_PAIR,
        ACTIVITY_KIND_USER_TEXT,
    ]
    assert episodes[0].byte_end == 1_000_000
    assert episodes[0].tool_pair_count == 1


def test_activities_are_sorted_by_source_order_when_input_is_shuffled() -> None:
    first = activity(1, byte_start=100, sequence=1)
    second = activity(2, byte_start=100, sequence=2)
    third = activity(3, byte_start=300, sequence=0)

    episodes = segment_activities([third, second, first])

    assert len(episodes) == 1
    assert [item.source_entry_ids for item in episodes[0].activities] == [
        (1,),
        (2,),
        (3,),
    ]


def test_aggregate_fields_cover_episode_activities() -> None:
    early_timestamp = BASE_TIME - timedelta(minutes=10)
    late_timestamp = BASE_TIME + timedelta(minutes=10)
    first = activity(
        10,
        ACTIVITY_KIND_SESSION_EVENT,
        byte_start=500,
        byte_end=525,
        timestamp_start=None,
        timestamp_end=None,
        source_entry_ids=(),
        sequence=0,
    )
    second = activity(
        11,
        ACTIVITY_KIND_USER_TEXT,
        byte_start=600,
        byte_end=650,
        timestamp_start=BASE_TIME,
        timestamp_end=late_timestamp,
        sequence=1,
    )
    third = activity(
        12,
        ACTIVITY_KIND_TOOL_PAIR,
        byte_start=550,
        byte_end=700,
        timestamp_start=early_timestamp,
        timestamp_end=BASE_TIME,
        source_entry_ids=(12, 13),
        sequence=2,
    )
    fourth = activity(
        14,
        ACTIVITY_KIND_CUSTOM_EVENT,
        byte_start=800,
        byte_end=900,
        timestamp_start=None,
        timestamp_end=None,
        sequence=3,
    )

    episodes = segment_activities([first, second, third, fourth])

    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.first_entry_id == 12
    assert episode.last_entry_id == 14
    assert episode.byte_start == 500
    assert episode.byte_end == 900
    assert episode.timestamp_start == early_timestamp
    assert episode.timestamp_end == late_timestamp
    assert episode.activity_count == 4
    assert episode.message_count == 1
    assert episode.tool_pair_count == 1
