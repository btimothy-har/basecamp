"""Deterministic Phase 5A episode manifest builders."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pi_memory.analysis.activity import NormalizedActivity
from pi_memory.analysis.episodes import NormalizedEpisode
from pi_memory.db import (
    ACTIVITY_KIND_ASSISTANT_TEXT,
    ACTIVITY_KIND_ASSISTANT_THINKING,
    ACTIVITY_KIND_CUSTOM_EVENT,
    ACTIVITY_KIND_ORPHAN_TOOL_RESULT,
    ACTIVITY_KIND_TOOL_PAIR,
    ACTIVITY_KIND_USER_TEXT,
    SESSION_SNAPSHOT_STATUS_READY_FOR_INTERPRETATION,
    SOURCE_ORIGIN_LOCAL,
    SOURCE_ORIGIN_MIXED,
    SOURCE_ORIGIN_UNKNOWN,
    SOURCE_ORIGINS,
)

MANIFEST_VERSION = 1
SNAPSHOT_SHELL_VERSION = 1
MAX_MANIFEST_ACTIVITIES = 100
MANIFEST_HEAD_ACTIVITIES = 80
MANIFEST_TAIL_ACTIVITIES = 20
MAX_MANIFEST_STRING_CHARS = 500
CLAIM_SOURCE_ACTIVITY_KINDS = frozenset(
    {
        ACTIVITY_KIND_USER_TEXT,
        ACTIVITY_KIND_ASSISTANT_TEXT,
        ACTIVITY_KIND_ASSISTANT_THINKING,
        ACTIVITY_KIND_TOOL_PAIR,
        ACTIVITY_KIND_ORPHAN_TOOL_RESULT,
        ACTIVITY_KIND_CUSTOM_EVENT,
    },
)


@dataclass(frozen=True)
class ForkProvenance:
    """Transcript fork provenance context for snapshot readiness."""

    parent_transcript_path: str | None = None
    parent_transcript_id: int | None = None


@dataclass(frozen=True)
class BuiltEpisodeManifest:
    """Pure episode manifest payload ready for future persistence."""

    episode_ordinal: int
    manifest_version: int
    activity_count: int
    tool_pair_count: int
    first_entry_id: int | None
    last_entry_id: int | None
    byte_start: int
    byte_end: int
    activity_map_json: dict[str, Any]
    source_spans_json: list[dict[str, Any]]
    tool_result_text_byte_count: int


@dataclass(frozen=True)
class BuiltSessionSnapshotShell:
    """Pure session snapshot shell payload ready for future persistence."""

    status: str
    analyzed_through_entry_id: int | None
    analyzed_through_byte_offset: int
    activity_count: int
    episode_count: int
    manifest_count: int
    tool_pair_count: int
    snapshot_json: dict[str, Any]


def build_episode_manifest(episode: NormalizedEpisode) -> BuiltEpisodeManifest:
    """Build a deterministic bounded manifest for one normalized episode."""
    included_activities = _included_activities(episode.activities)
    activity_maps = [_activity_map(index=index, activity=activity) for index, activity in included_activities]
    origin_counts = _activity_origin_counts(episode.activities)
    activity_map_json = {
        "kind": "episode_manifest_activity_map",
        "version": MANIFEST_VERSION,
        "episode": _episode_metadata(episode),
        "activity_count": episode.activity_count,
        "included_activity_count": len(activity_maps),
        "omitted_activity_count": episode.activity_count - len(activity_maps),
        "included_ranges": _included_ranges(included_activities),
        "omitted_ranges": _omitted_ranges(episode.activity_count, included_activities),
        "origin_counts": origin_counts,
        "claim_source_activity_count": _claim_source_activity_count(episode.activities),
        "activities": activity_maps,
    }
    return BuiltEpisodeManifest(
        episode_ordinal=episode.ordinal,
        manifest_version=MANIFEST_VERSION,
        activity_count=episode.activity_count,
        tool_pair_count=episode.tool_pair_count,
        first_entry_id=episode.first_entry_id,
        last_entry_id=episode.last_entry_id,
        byte_start=episode.byte_start,
        byte_end=episode.byte_end,
        activity_map_json=activity_map_json,
        source_spans_json=_source_spans(episode, included_activities),
        tool_result_text_byte_count=sum(activity.result_text_byte_count for activity in episode.activities),
    )


def build_episode_manifests(
    episodes: Sequence[NormalizedEpisode],
) -> list[BuiltEpisodeManifest]:
    """Build deterministic manifests for normalized episodes."""
    return [build_episode_manifest(episode) for episode in episodes]


def build_session_snapshot_shell(
    episodes: Sequence[NormalizedEpisode],
    manifests: Sequence[BuiltEpisodeManifest],
    fork_provenance: ForkProvenance | None = None,
) -> BuiltSessionSnapshotShell:
    """Build a deterministic no-claims session snapshot shell."""
    status = SESSION_SNAPSHOT_STATUS_READY_FOR_INTERPRETATION
    provenance = fork_provenance or ForkProvenance()
    activities = [activity for episode in episodes for activity in episode.activities]
    activity_count = sum(episode.activity_count for episode in episodes)
    tool_pair_count = sum(episode.tool_pair_count for episode in episodes)
    origin_counts = _activity_origin_counts(activities)
    claim_source_activity_count = _claim_source_activity_count(activities)
    fork_json = _fork_json(provenance, origin_counts)
    ready_for_interpretation = fork_json["blocked_reason"] is None
    analyzed_through_entry_id = _analyzed_through_entry_id(episodes)
    analyzed_through_byte_offset = max(
        (episode.byte_end for episode in episodes),
        default=0,
    )
    snapshot_json = {
        "kind": "session_snapshot_shell",
        "version": SNAPSHOT_SHELL_VERSION,
        "ready_for_interpretation": ready_for_interpretation,
        "status": status,
        "fork": fork_json,
        "counts": {
            "activity_count": activity_count,
            "episode_count": len(episodes),
            "manifest_count": len(manifests),
            "tool_pair_count": tool_pair_count,
            **origin_counts,
            "claim_source_activity_count": claim_source_activity_count,
        },
        "analyzed_through": {
            "entry_id": analyzed_through_entry_id,
            "byte_offset": analyzed_through_byte_offset,
        },
        "episodes": [
            {
                "ordinal": episode.ordinal,
                "status": episode.status,
                "close_reason": episode.close_reason,
            }
            for episode in episodes
        ],
    }
    return BuiltSessionSnapshotShell(
        status=status,
        analyzed_through_entry_id=analyzed_through_entry_id,
        analyzed_through_byte_offset=analyzed_through_byte_offset,
        activity_count=activity_count,
        episode_count=len(episodes),
        manifest_count=len(manifests),
        tool_pair_count=tool_pair_count,
        snapshot_json=snapshot_json,
    )


def _episode_metadata(episode: NormalizedEpisode) -> dict[str, Any]:
    return {
        "ordinal": episode.ordinal,
        "status": episode.status,
        "close_reason": episode.close_reason,
        "activity_count": episode.activity_count,
        "message_count": episode.message_count,
        "tool_pair_count": episode.tool_pair_count,
        "byte_start": episode.byte_start,
        "byte_end": episode.byte_end,
        "first_entry_id": episode.first_entry_id,
        "last_entry_id": episode.last_entry_id,
        "timestamp_start": _isoformat(episode.timestamp_start),
        "timestamp_end": _isoformat(episode.timestamp_end),
        "boundary_metadata": _bounded_json(episode.boundary_metadata),
    }


def _activity_map(index: int, activity: NormalizedActivity) -> dict[str, Any]:
    return {
        "index": index,
        "sequence": activity.sequence,
        "kind": activity.kind,
        "source_entry_ids": list(activity.source_entry_ids),
        "byte_start": activity.byte_start,
        "byte_end": activity.byte_end,
        "timestamp_start": _isoformat(activity.timestamp_start),
        "timestamp_end": _isoformat(activity.timestamp_end),
        "message_role": activity.message_role,
        "tool_call_id": activity.tool_call_id,
        "tool_name": activity.tool_name,
        "is_error": activity.is_error,
        "source_origin": activity.source_origin,
        "claim_source_allowed": _claim_source_allowed(activity),
        "raw_text_available": activity.raw_text_available,
        "text_char_count": activity.text_char_count,
        "result_text_byte_count": activity.result_text_byte_count,
        "result_text_line_count": activity.result_text_line_count,
        "receipt_json": _bounded_json(activity.receipt_json),
        "source_metadata_json": _bounded_json(activity.source_metadata_json),
    }


def _source_spans(
    episode: NormalizedEpisode,
    included_activities: Sequence[tuple[int, NormalizedActivity]],
) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = [
        {
            "kind": "episode",
            "episode_ordinal": episode.ordinal,
            "byte_start": episode.byte_start,
            "byte_end": episode.byte_end,
            "first_entry_id": episode.first_entry_id,
            "last_entry_id": episode.last_entry_id,
            "timestamp_start": _isoformat(episode.timestamp_start),
            "timestamp_end": _isoformat(episode.timestamp_end),
        },
    ]
    spans.extend(
        {
            "kind": "activity",
            "episode_ordinal": episode.ordinal,
            "activity_index": index,
            "sequence": activity.sequence,
            "activity_kind": activity.kind,
            "source_entry_ids": list(activity.source_entry_ids),
            "byte_start": activity.byte_start,
            "byte_end": activity.byte_end,
            "timestamp_start": _isoformat(activity.timestamp_start),
            "timestamp_end": _isoformat(activity.timestamp_end),
        }
        for index, activity in included_activities
    )
    return spans


def _included_activities(
    activities: Sequence[NormalizedActivity],
) -> list[tuple[int, NormalizedActivity]]:
    indexed = list(enumerate(activities))
    if len(indexed) <= MAX_MANIFEST_ACTIVITIES:
        return indexed
    return [
        *indexed[:MANIFEST_HEAD_ACTIVITIES],
        *indexed[-MANIFEST_TAIL_ACTIVITIES:],
    ]


def _included_ranges(
    included_activities: Sequence[tuple[int, NormalizedActivity]],
) -> list[dict[str, int]]:
    if not included_activities:
        return []

    ranges: list[dict[str, int]] = []
    start = previous = included_activities[0][0]
    for index, _activity in included_activities[1:]:
        if index == previous + 1:
            previous = index
            continue
        ranges.append(_range(start, previous))
        start = previous = index
    ranges.append(_range(start, previous))
    return ranges


def _omitted_ranges(
    activity_count: int,
    included_activities: Sequence[tuple[int, NormalizedActivity]],
) -> list[dict[str, int]]:
    if activity_count == len(included_activities):
        return []

    included_indexes = {index for index, _activity in included_activities}
    ranges: list[dict[str, int]] = []
    start: int | None = None
    previous: int | None = None
    for index in range(activity_count):
        if index in included_indexes:
            if start is not None and previous is not None:
                ranges.append(_range(start, previous))
                start = previous = None
            continue
        if start is None:
            start = previous = index
        else:
            previous = index
    if start is not None and previous is not None:
        ranges.append(_range(start, previous))
    return ranges


def _range(start: int, end: int) -> dict[str, int]:
    return {
        "start_index": start,
        "end_index": end,
        "count": end - start + 1,
    }


def _activity_origin_counts(activities: Sequence[NormalizedActivity]) -> dict[str, int]:
    counts = {f"{origin}_activity_count": 0 for origin in SOURCE_ORIGINS}
    for activity in activities:
        origin = activity.source_origin
        if origin not in SOURCE_ORIGINS:
            origin = SOURCE_ORIGIN_UNKNOWN
        counts[f"{origin}_activity_count"] += 1
    return counts


def _claim_source_activity_count(activities: Sequence[NormalizedActivity]) -> int:
    return sum(1 for activity in activities if _claim_source_allowed(activity))


def _claim_source_allowed(activity: NormalizedActivity) -> bool:
    return (
        activity.source_origin in {SOURCE_ORIGIN_LOCAL, SOURCE_ORIGIN_MIXED}
        and activity.kind in CLAIM_SOURCE_ACTIVITY_KINDS
    )


def _fork_json(provenance: ForkProvenance, origin_counts: dict[str, int]) -> dict[str, Any]:
    has_parent = provenance.parent_transcript_path is not None
    parent_resolved = not has_parent or provenance.parent_transcript_id is not None
    source_origin_complete = parent_resolved and origin_counts[f"{SOURCE_ORIGIN_UNKNOWN}_activity_count"] == 0
    blocked_reason = _blocked_reason(
        parent_resolved=parent_resolved,
        source_origin_complete=source_origin_complete,
    )
    return {
        "has_parent": has_parent,
        "parent_transcript_path": provenance.parent_transcript_path,
        "parent_transcript_id": provenance.parent_transcript_id,
        "parent_resolved": parent_resolved,
        "source_origin_complete": source_origin_complete,
        "blocked_reason": blocked_reason,
    }


def _blocked_reason(*, parent_resolved: bool, source_origin_complete: bool) -> str | None:
    if not parent_resolved:
        return "parent_transcript_not_ingested"
    if not source_origin_complete:
        return "source_origin_incomplete"
    return None


def _analyzed_through_entry_id(episodes: Sequence[NormalizedEpisode]) -> int | None:
    for episode in reversed(episodes):
        if episode.last_entry_id is not None:
            return episode.last_entry_id
    return None


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _bounded_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _bounded_json(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, tuple | list):
        return [_bounded_json(item) for item in value]
    if isinstance(value, str):
        return _bounded_string(value)
    if value is None or isinstance(value, bool | int | float):
        return value
    return _bounded_string(str(value))


def _bounded_string(value: str) -> str | dict[str, Any]:
    if len(value) <= MAX_MANIFEST_STRING_CHARS:
        return value
    return {
        "omitted": True,
        "char_count": len(value),
        "byte_count": len(value.encode("utf-8")),
    }
