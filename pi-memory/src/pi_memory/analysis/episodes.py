"""Deterministic Phase 5A episode segmentation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pi_memory.analysis.activity import NormalizedActivity
from pi_memory.db import (
    ACTIVITY_KIND_ASSISTANT_TEXT,
    ACTIVITY_KIND_ASSISTANT_THINKING,
    ACTIVITY_KIND_COMPACTION,
    ACTIVITY_KIND_TOOL_PAIR,
    ACTIVITY_KIND_USER_TEXT,
    EPISODE_CLOSE_REASON_COMPACTION,
    EPISODE_CLOSE_REASON_CURRENT_CURSOR,
    EPISODE_CLOSE_REASON_TIME_GAP,
    EPISODE_STATUS_CLOSED,
    EPISODE_STATUS_OPEN,
)

MESSAGE_ACTIVITY_KINDS = frozenset(
    {
        ACTIVITY_KIND_USER_TEXT,
        ACTIVITY_KIND_ASSISTANT_TEXT,
        ACTIVITY_KIND_ASSISTANT_THINKING,
    },
)


@dataclass(frozen=True)
class NormalizedEpisode:
    """Pure episode unit ready for future persistence."""

    ordinal: int
    status: str
    close_reason: str
    activities: tuple[NormalizedActivity, ...]
    first_entry_id: int | None
    last_entry_id: int | None
    byte_start: int
    byte_end: int
    timestamp_start: datetime | None
    timestamp_end: datetime | None
    activity_count: int
    message_count: int
    tool_pair_count: int
    boundary_metadata: dict[str, Any]


def segment_activities(
    activities: Sequence[NormalizedActivity],
    *,
    gap_threshold: timedelta = timedelta(hours=1),
    final_close_reason: str = EPISODE_CLOSE_REASON_CURRENT_CURSOR,
) -> list[NormalizedEpisode]:
    """Segment normalized activities into deterministic structural episodes.

    Args:
        activities: Activities from one transcript/session scope. They are sorted by
            ``(byte_start, sequence)`` before segmentation.
        gap_threshold: Minimum timestamp gap that closes the current episode.
        final_close_reason: Close reason assigned to the final open episode.

    Returns:
        Episode summaries whose boundaries are only structural/lifecycle events.
    """
    ordered = sorted(activities, key=lambda activity: (activity.byte_start, activity.sequence))
    if not ordered:
        return []

    episodes: list[NormalizedEpisode] = []
    current: list[NormalizedActivity] = []
    previous: NormalizedActivity | None = None

    for activity in ordered:
        if current and previous is not None and activity.kind != ACTIVITY_KIND_COMPACTION:
            gap_seconds = _gap_seconds(previous, activity, gap_threshold)
            if gap_seconds is not None:
                episodes.append(
                    _episode(
                        ordinal=len(episodes),
                        activities=current,
                        close_reason=EPISODE_CLOSE_REASON_TIME_GAP,
                        status=EPISODE_STATUS_CLOSED,
                        boundary_metadata={"gap_seconds": gap_seconds},
                    ),
                )
                current = []

        current.append(activity)

        if activity.kind == ACTIVITY_KIND_COMPACTION:
            episodes.append(
                _episode(
                    ordinal=len(episodes),
                    activities=current,
                    close_reason=EPISODE_CLOSE_REASON_COMPACTION,
                    status=EPISODE_STATUS_CLOSED,
                    boundary_metadata={
                        "source_entry_ids": activity.source_entry_ids,
                        "source_metadata_json": activity.source_metadata_json,
                    },
                ),
            )
            current = []

        previous = activity

    if current:
        status = (
            EPISODE_STATUS_OPEN
            if final_close_reason == EPISODE_CLOSE_REASON_CURRENT_CURSOR
            else EPISODE_STATUS_CLOSED
        )
        episodes.append(
            _episode(
                ordinal=len(episodes),
                activities=current,
                close_reason=final_close_reason,
                status=status,
                boundary_metadata={},
            ),
        )

    return episodes


def _gap_seconds(
    previous: NormalizedActivity,
    current: NormalizedActivity,
    threshold: timedelta,
) -> float | None:
    if previous.timestamp_end is None or current.timestamp_start is None:
        return None

    gap = current.timestamp_start - previous.timestamp_end
    if gap < threshold:
        return None

    return gap.total_seconds()


def _episode(
    *,
    ordinal: int,
    activities: Sequence[NormalizedActivity],
    close_reason: str,
    status: str,
    boundary_metadata: dict[str, Any],
) -> NormalizedEpisode:
    episode_activities = tuple(activities)
    return NormalizedEpisode(
        ordinal=ordinal,
        status=status,
        close_reason=close_reason,
        activities=episode_activities,
        first_entry_id=_first_entry_id(episode_activities),
        last_entry_id=_last_entry_id(episode_activities),
        byte_start=min(activity.byte_start for activity in episode_activities),
        byte_end=max(activity.byte_end for activity in episode_activities),
        timestamp_start=_min_timestamp(episode_activities),
        timestamp_end=_max_timestamp(episode_activities),
        activity_count=len(episode_activities),
        message_count=sum(
            1 for activity in episode_activities if activity.kind in MESSAGE_ACTIVITY_KINDS
        ),
        tool_pair_count=sum(
            1 for activity in episode_activities if activity.kind == ACTIVITY_KIND_TOOL_PAIR
        ),
        boundary_metadata=boundary_metadata,
    )


def _first_entry_id(activities: Sequence[NormalizedActivity]) -> int | None:
    for activity in activities:
        if activity.source_entry_ids:
            return activity.source_entry_ids[0]
    return None


def _last_entry_id(activities: Sequence[NormalizedActivity]) -> int | None:
    for activity in reversed(activities):
        if activity.source_entry_ids:
            return activity.source_entry_ids[-1]
    return None


def _min_timestamp(activities: Sequence[NormalizedActivity]) -> datetime | None:
    timestamps = [
        timestamp
        for activity in activities
        for timestamp in (activity.timestamp_start, activity.timestamp_end)
        if timestamp is not None
    ]
    return min(timestamps) if timestamps else None


def _max_timestamp(activities: Sequence[NormalizedActivity]) -> datetime | None:
    timestamps = [
        timestamp
        for activity in activities
        for timestamp in (activity.timestamp_start, activity.timestamp_end)
        if timestamp is not None
    ]
    return max(timestamps) if timestamps else None
