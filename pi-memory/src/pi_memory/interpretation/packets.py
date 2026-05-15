"""Read-only packet builders for future session interpretation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pi_memory.analysis.manifests import CLAIM_SOURCE_ACTIVITY_KINDS
from pi_memory.db import (
    ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    ANALYSIS_STATUS_COMPLETED,
    SESSION_INTERPRETATION_BLOCKED_REASON_PARENT_TRANSCRIPT_NOT_INGESTED,
    SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY,
    SESSION_INTERPRETATION_BLOCKED_REASON_SOURCE_ORIGIN_INCOMPLETE,
    SOURCE_ORIGIN_LOCAL,
    SOURCE_ORIGIN_MIXED,
    SOURCE_ORIGIN_UNKNOWN,
    ActivityUnit,
    AnalysisRun,
    Episode,
    EpisodeManifest,
    MemorySession,
    Transcript,
    TranscriptEntry,
)

SOURCE_EXCERPT_CHAR_LIMIT = 500
MANIFEST_METADATA_CHAR_LIMIT = 500
ORIGIN_COUNT_KEYS = (
    "local_activity_count",
    "inherited_activity_count",
    "mixed_activity_count",
    "unknown_activity_count",
)


@dataclass(frozen=True)
class BoundedText:
    """A safely bounded text excerpt with truncation metadata."""

    text: str
    original_char_count: int
    original_byte_count: int
    is_truncated: bool
    omitted_char_count: int
    omitted_byte_count: int


@dataclass(frozen=True)
class SourceRef:
    """Citation-ready transcript source reference for an included activity."""

    source_ref_id: str
    activity_unit_id: int
    episode_id: int
    episode_ordinal: int
    activity_index: int
    activity_kind: str
    source_origin: str
    claim_source_allowed: bool
    source_entry_row_ids: tuple[int, ...]
    byte_start: int
    byte_end: int
    excerpts: tuple[BoundedText, ...]
    receipt_metadata: Mapping[str, Any]
    source_metadata: Mapping[str, Any]


@dataclass(frozen=True)
class ActivityPacket:
    """Bounded included activity payload copied from an episode manifest."""

    activity_unit_id: int
    episode_id: int
    episode_ordinal: int
    activity_index: int
    sequence: int | None
    kind: str
    source_origin: str
    claim_source_allowed: bool
    source_entry_row_ids: tuple[int, ...]
    byte_start: int
    byte_end: int
    message_role: str | None
    tool_call_id: str | None
    tool_name: str | None
    is_error: bool | None
    text_char_count: int
    result_text_byte_count: int
    result_text_line_count: int
    receipt_metadata: Mapping[str, Any]
    source_metadata: Mapping[str, Any]
    source_refs: tuple[SourceRef, ...]


@dataclass(frozen=True)
class InterpretationReadiness:
    """Read-only readiness derived directly from Phase 5A rows."""

    session_row_id: int
    stable_session_id: str
    transcript_id: int
    latest_analysis_run_id: int | None
    requested_analysis_run_id: int | None
    is_stale: bool
    is_ready: bool
    blocked_reason: str | None
    origin_counts: Mapping[str, int]
    claim_source_activity_count: int
    activity_count: int
    episode_count: int
    manifest_count: int
    analyzed_through_entry_id: int | None
    analyzed_through_byte_offset: int

    @property
    def should_skip_model(self) -> bool:
        """Whether interpretation should skip LLM calls due to no sources."""
        return self.is_ready and self.claim_source_activity_count == 0

    @property
    def can_call_model(self) -> bool:
        """Whether future job flow may safely call an interpretation model."""
        return self.is_ready and not self.is_stale and self.claim_source_activity_count > 0


@dataclass(frozen=True)
class EpisodePacket:
    """Bounded episode packet suitable for future interpretation prompts."""

    episode_id: int
    manifest_id: int
    ordinal: int
    status: str
    close_reason: str | None
    byte_start: int
    byte_end: int
    activity_count: int
    message_count: int
    tool_pair_count: int
    included_ranges: tuple[Mapping[str, int], ...]
    omitted_ranges: tuple[Mapping[str, int], ...]
    origin_counts: Mapping[str, int]
    claim_source_activity_count: int
    tool_result_text_byte_count: int
    included_activities: tuple[ActivityPacket, ...]
    source_refs: tuple[SourceRef, ...]


@dataclass(frozen=True)
class InterpretationPacket:
    """Session interpretation input assembled from persisted rows."""

    session_metadata: Mapping[str, Any]
    transcript_metadata: Mapping[str, Any]
    source_analysis_metadata: Mapping[str, Any]
    readiness: InterpretationReadiness
    episode_packets: tuple[EpisodePacket, ...]


def build_interpretation_packet(
    session: Session,
    transcript: Transcript,
    analysis_run_id: int | None = None,
) -> InterpretationPacket:
    """Build read-only readiness and bounded episode packets for a transcript.

    Args:
        session: Active SQLAlchemy session. The builder only reads from it.
        transcript: Transcript whose completed Phase 5A rows should be used.
        analysis_run_id: Optional requested analysis run id. If it is not the
            latest completed run for the transcript, readiness is marked stale
            and episode packets are omitted.

    Returns:
        Interpretation packet read model.
    """
    memory_session = session.get(MemorySession, transcript.session_id)
    latest_run = _latest_completed_analysis_run(session, transcript.id)
    is_stale = analysis_run_id is not None and (
        latest_run is None or analysis_run_id != latest_run.id
    )
    active_run = None if is_stale else latest_run
    readiness = _readiness(
        session=session,
        transcript=transcript,
        memory_session=memory_session,
        latest_run=latest_run,
        active_run=active_run,
        requested_analysis_run_id=analysis_run_id,
        is_stale=is_stale,
    )
    episode_packets = () if is_stale or latest_run is None else _episode_packets(session, latest_run.id)
    return InterpretationPacket(
        session_metadata=_session_metadata(memory_session, transcript),
        transcript_metadata=_transcript_metadata(transcript),
        source_analysis_metadata=_analysis_metadata(latest_run),
        readiness=readiness,
        episode_packets=episode_packets,
    )


def _latest_completed_analysis_run(session: Session, transcript_id: int) -> AnalysisRun | None:
    return session.scalar(
        select(AnalysisRun)
        .where(
            AnalysisRun.transcript_id == transcript_id,
            AnalysisRun.analysis_kind == ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
            AnalysisRun.status == ANALYSIS_STATUS_COMPLETED,
        )
        .order_by(AnalysisRun.id.desc())
        .limit(1),
    )


def _readiness(
    *,
    session: Session,
    transcript: Transcript,
    memory_session: MemorySession | None,
    latest_run: AnalysisRun | None,
    active_run: AnalysisRun | None,
    requested_analysis_run_id: int | None,
    is_stale: bool,
) -> InterpretationReadiness:
    origin_counts = _origin_counts(session, active_run.id) if active_run is not None else _empty_origin_counts()
    claim_source_activity_count = _claim_source_activity_count(session, active_run.id) if active_run is not None else 0
    blocked_reason = _blocked_reason(
        transcript=transcript,
        latest_run=latest_run,
        active_run=active_run,
        origin_counts=origin_counts,
        is_stale=is_stale,
    )
    return InterpretationReadiness(
        session_row_id=transcript.session_id,
        stable_session_id=memory_session.session_id if memory_session is not None else "",
        transcript_id=transcript.id,
        latest_analysis_run_id=latest_run.id if latest_run is not None else None,
        requested_analysis_run_id=requested_analysis_run_id,
        is_stale=is_stale,
        is_ready=blocked_reason is None and not is_stale and latest_run is not None,
        blocked_reason=blocked_reason,
        origin_counts=origin_counts,
        claim_source_activity_count=claim_source_activity_count,
        activity_count=active_run.activity_count if active_run is not None else 0,
        episode_count=active_run.episode_count if active_run is not None else 0,
        manifest_count=active_run.manifest_count if active_run is not None else 0,
        analyzed_through_entry_id=active_run.analyzed_through_entry_id if active_run is not None else None,
        analyzed_through_byte_offset=active_run.analyzed_through_byte_offset if active_run is not None else 0,
    )


def _blocked_reason(
    *,
    transcript: Transcript,
    latest_run: AnalysisRun | None,
    active_run: AnalysisRun | None,
    origin_counts: Mapping[str, int],
    is_stale: bool,
) -> str | None:
    if latest_run is None:
        return SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY
    if is_stale:
        return None
    if transcript.parent_transcript_path is not None and transcript.parent_transcript_id is None:
        return SESSION_INTERPRETATION_BLOCKED_REASON_PARENT_TRANSCRIPT_NOT_INGESTED
    if active_run is not None and origin_counts[f"{SOURCE_ORIGIN_UNKNOWN}_activity_count"] > 0:
        return SESSION_INTERPRETATION_BLOCKED_REASON_SOURCE_ORIGIN_INCOMPLETE
    return None


def _origin_counts(session: Session, analysis_run_id: int) -> dict[str, int]:
    counts = _empty_origin_counts()
    rows = session.execute(
        select(ActivityUnit.source_origin, func.count())
        .where(ActivityUnit.analysis_run_id == analysis_run_id)
        .group_by(ActivityUnit.source_origin),
    )
    for origin, count in rows:
        key = f"{origin}_activity_count"
        if key not in counts:
            key = f"{SOURCE_ORIGIN_UNKNOWN}_activity_count"
        counts[key] += int(count)
    return counts


def _empty_origin_counts() -> dict[str, int]:
    return dict.fromkeys(ORIGIN_COUNT_KEYS, 0)


def _claim_source_activity_count(session: Session, analysis_run_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(ActivityUnit)
            .where(
                ActivityUnit.analysis_run_id == analysis_run_id,
                ActivityUnit.source_origin.in_((SOURCE_ORIGIN_LOCAL, SOURCE_ORIGIN_MIXED)),
                ActivityUnit.kind.in_(tuple(CLAIM_SOURCE_ACTIVITY_KINDS)),
            ),
        )
        or 0,
    )


def _episode_packets(session: Session, analysis_run_id: int) -> tuple[EpisodePacket, ...]:
    rows = session.execute(
        select(Episode, EpisodeManifest)
        .join(EpisodeManifest, EpisodeManifest.episode_id == Episode.id)
        .where(Episode.analysis_run_id == analysis_run_id)
        .order_by(Episode.ordinal),
    ).all()
    packets: list[EpisodePacket] = []
    for episode, manifest in rows:
        activity_packets = _activity_packets(session, episode, manifest)
        source_refs = tuple(ref for activity in activity_packets for ref in activity.source_refs)
        activity_map = _activity_map(manifest)
        packets.append(
            EpisodePacket(
                episode_id=episode.id,
                manifest_id=manifest.id,
                ordinal=episode.ordinal,
                status=episode.status,
                close_reason=episode.close_reason,
                byte_start=episode.byte_start,
                byte_end=episode.byte_end,
                activity_count=episode.activity_count,
                message_count=episode.message_count,
                tool_pair_count=episode.tool_pair_count,
                included_ranges=_tuple_of_mappings(activity_map.get("included_ranges")),
                omitted_ranges=_tuple_of_mappings(activity_map.get("omitted_ranges")),
                origin_counts=_manifest_origin_counts(activity_map),
                claim_source_activity_count=int(activity_map.get("claim_source_activity_count") or 0),
                tool_result_text_byte_count=manifest.tool_result_text_byte_count,
                included_activities=activity_packets,
                source_refs=source_refs,
            ),
        )
    return tuple(packets)


def _activity_packets(
    session: Session,
    episode: Episode,
    manifest: EpisodeManifest,
) -> tuple[ActivityPacket, ...]:
    activities = _included_manifest_activities(manifest)
    units = _activity_units_by_ordinal(
        session=session,
        analysis_run_id=episode.analysis_run_id,
        episode_id=episode.id,
        ordinals=[int(activity["index"]) for activity in activities if "index" in activity],
    )
    entries = _entries_by_id(session, _source_entry_ids(activities))
    packets: list[ActivityPacket] = []
    for activity in activities:
        index = int(activity.get("index", 0))
        unit = units.get(index)
        if unit is None:
            continue
        receipt_metadata = _bounded_json(activity.get("receipt_json") or {})
        source_metadata = _bounded_json(activity.get("source_metadata_json") or {})
        source_refs = _source_refs(
            activity=activity,
            unit=unit,
            episode=episode,
            entries=entries,
            receipt_metadata=receipt_metadata,
            source_metadata=source_metadata,
        )
        packets.append(
            ActivityPacket(
                activity_unit_id=unit.id,
                episode_id=episode.id,
                episode_ordinal=episode.ordinal,
                activity_index=index,
                sequence=_optional_int(activity.get("sequence")),
                kind=str(activity.get("kind") or unit.kind),
                source_origin=str(activity.get("source_origin") or unit.source_origin),
                claim_source_allowed=bool(activity.get("claim_source_allowed")),
                source_entry_row_ids=tuple(int(value) for value in activity.get("source_entry_ids") or ()),
                byte_start=int(activity.get("byte_start") or unit.byte_start),
                byte_end=int(activity.get("byte_end") or unit.byte_end),
                message_role=_optional_str(activity.get("message_role")),
                tool_call_id=_optional_str(activity.get("tool_call_id")),
                tool_name=_optional_str(activity.get("tool_name")),
                is_error=activity.get("is_error") if isinstance(activity.get("is_error"), bool) else None,
                text_char_count=int(activity.get("text_char_count") or 0),
                result_text_byte_count=int(activity.get("result_text_byte_count") or 0),
                result_text_line_count=int(activity.get("result_text_line_count") or 0),
                receipt_metadata=receipt_metadata,
                source_metadata=source_metadata,
                source_refs=source_refs,
            ),
        )
    return tuple(packets)


def _activity_units_by_ordinal(
    *,
    session: Session,
    analysis_run_id: int,
    episode_id: int,
    ordinals: Iterable[int],
) -> dict[int, ActivityUnit]:
    wanted_ordinals = set(ordinals)
    if not wanted_ordinals:
        return {}
    units = session.scalars(
        select(ActivityUnit)
        .where(
            ActivityUnit.analysis_run_id == analysis_run_id,
            ActivityUnit.episode_id == episode_id,
        )
        .order_by(ActivityUnit.ordinal, ActivityUnit.id),
    )
    return {unit.ordinal: unit for unit in units if unit.ordinal in wanted_ordinals}


def _entries_by_id(session: Session, entry_ids: Iterable[int]) -> dict[int, TranscriptEntry]:
    row_ids = tuple(sorted(set(entry_ids)))
    if not row_ids:
        return {}
    entries = session.scalars(select(TranscriptEntry).where(TranscriptEntry.id.in_(row_ids)))
    return {entry.id: entry for entry in entries if entry.id is not None}


def _source_entry_ids(activities: Iterable[Mapping[str, Any]]) -> tuple[int, ...]:
    ids: list[int] = []
    for activity in activities:
        ids.extend(int(value) for value in activity.get("source_entry_ids") or ())
    return tuple(ids)


def _source_refs(
    *,
    activity: Mapping[str, Any],
    unit: ActivityUnit,
    episode: Episode,
    entries: Mapping[int, TranscriptEntry],
    receipt_metadata: Mapping[str, Any],
    source_metadata: Mapping[str, Any],
) -> tuple[SourceRef, ...]:
    row_ids = tuple(int(value) for value in activity.get("source_entry_ids") or ())
    excerpts = tuple(
        _bounded_text(entries[row_id].raw_line)
        for row_id in row_ids
        if row_id in entries
    )
    source_ref_id = (
        f"ar{unit.analysis_run_id}:ep{episode.ordinal}:act{unit.ordinal}:"
        f"entries{','.join(str(row_id) for row_id in row_ids) or 'none'}"
    )
    return (
        SourceRef(
            source_ref_id=source_ref_id,
            activity_unit_id=unit.id,
            episode_id=episode.id,
            episode_ordinal=episode.ordinal,
            activity_index=int(activity.get("index") or 0),
            activity_kind=str(activity.get("kind") or unit.kind),
            source_origin=str(activity.get("source_origin") or unit.source_origin),
            claim_source_allowed=bool(activity.get("claim_source_allowed")),
            source_entry_row_ids=row_ids,
            byte_start=int(activity.get("byte_start") or unit.byte_start),
            byte_end=int(activity.get("byte_end") or unit.byte_end),
            excerpts=excerpts,
            receipt_metadata=receipt_metadata,
            source_metadata=source_metadata,
        ),
    )


def _included_manifest_activities(manifest: EpisodeManifest) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        activity
        for activity in _activity_map(manifest).get("activities", [])
        if isinstance(activity, Mapping)
    )


def _activity_map(manifest: EpisodeManifest) -> Mapping[str, Any]:
    if isinstance(manifest.activity_map_json, Mapping):
        return manifest.activity_map_json
    return {}


def _manifest_origin_counts(activity_map: Mapping[str, Any]) -> dict[str, int]:
    value = activity_map.get("origin_counts")
    if not isinstance(value, Mapping):
        return _empty_origin_counts()
    counts = _empty_origin_counts()
    for key in counts:
        counts[key] = int(value.get(key) or 0)
    return counts


def _tuple_of_mappings(value: Any) -> tuple[Mapping[str, int], ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _bounded_text(value: str, limit: int = SOURCE_EXCERPT_CHAR_LIMIT) -> BoundedText:
    text = value[:limit]
    original_bytes = len(value.encode("utf-8"))
    excerpt_bytes = len(text.encode("utf-8"))
    return BoundedText(
        text=text,
        original_char_count=len(value),
        original_byte_count=original_bytes,
        is_truncated=len(value) > limit,
        omitted_char_count=max(len(value) - len(text), 0),
        omitted_byte_count=max(original_bytes - excerpt_bytes, 0),
    )


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
    if len(value) <= MANIFEST_METADATA_CHAR_LIMIT:
        return value
    return {
        "omitted": True,
        "char_count": len(value),
        "byte_count": len(value.encode("utf-8")),
    }


def _session_metadata(
    memory_session: MemorySession | None,
    transcript: Transcript,
) -> Mapping[str, Any]:
    if memory_session is None:
        return {"session_row_id": transcript.session_id, "stable_session_id": ""}
    return {
        "session_row_id": memory_session.id,
        "stable_session_id": memory_session.session_id,
        "cwd": memory_session.cwd,
        "repo_name": memory_session.repo_name,
        "repo_root": memory_session.repo_root,
        "worktree_label": memory_session.worktree_label,
        "worktree_path": memory_session.worktree_path,
    }


def _transcript_metadata(transcript: Transcript) -> Mapping[str, Any]:
    return {
        "transcript_id": transcript.id,
        "path": transcript.path,
        "parent_transcript_path": transcript.parent_transcript_path,
        "parent_transcript_id": transcript.parent_transcript_id,
        "cursor_offset": transcript.cursor_offset,
        "file_size": transcript.file_size,
    }


def _analysis_metadata(analysis_run: AnalysisRun | None) -> Mapping[str, Any]:
    if analysis_run is None:
        return {
            "analysis_run_id": None,
            "analysis_kind": ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
            "status": None,
        }
    return {
        "analysis_run_id": analysis_run.id,
        "analysis_kind": analysis_run.analysis_kind,
        "status": analysis_run.status,
        "source_byte_start": analysis_run.source_byte_start,
        "source_byte_end": analysis_run.source_byte_end,
        "analyzed_through_entry_id": analysis_run.analyzed_through_entry_id,
        "analyzed_through_byte_offset": analysis_run.analyzed_through_byte_offset,
        "activity_count": analysis_run.activity_count,
        "episode_count": analysis_run.episode_count,
        "manifest_count": analysis_run.manifest_count,
        "started_at": _isoformat(analysis_run.started_at),
        "finished_at": _isoformat(analysis_run.finished_at),
    }


def _optional_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float | str) and str(value).isdigit() else None


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
