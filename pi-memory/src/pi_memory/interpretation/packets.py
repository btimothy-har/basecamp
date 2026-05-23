"""Read-only packet builders for future session interpretation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pi_memory.analysis.manifests import CLAIM_SOURCE_ACTIVITY_KINDS
from pi_memory.db.constants import (
    ACTIVITY_TEXT_STATUS_COMPLETED,
    ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    ANALYSIS_STATUS_COMPLETED,
    SESSION_INTERPRETATION_BLOCKED_REASON_PARENT_TRANSCRIPT_NOT_INGESTED,
    SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY,
    SESSION_INTERPRETATION_BLOCKED_REASON_SOURCE_ORIGIN_INCOMPLETE,
    SOURCE_ORIGIN_LOCAL,
    SOURCE_ORIGIN_MIXED,
    SOURCE_ORIGIN_UNKNOWN,
)
from pi_memory.db.models import (
    ActivityUnit,
    AnalysisRun,
    Episode,
    EpisodeManifest,
    MemorySession,
    Transcript,
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
    """Citation-ready activity-text source reference for an included activity."""

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
    """Chronological activity-text payload for session interpretation."""

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
    activity_text: str | None
    activity_text_kind: str
    activity_text_status: str
    activity_text_metadata: Mapping[str, Any]
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
    is_stale = analysis_run_id is not None and (latest_run is None or analysis_run_id != latest_run.id)
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


def build_episode_interpretation_packet(
    packet: InterpretationPacket,
    episode_packet: EpisodePacket,
) -> InterpretationPacket:
    """Return an interpretation packet scoped to one episode."""
    return InterpretationPacket(
        session_metadata=packet.session_metadata,
        transcript_metadata=packet.transcript_metadata,
        source_analysis_metadata={
            **dict(packet.source_analysis_metadata),
            "episode_id": episode_packet.episode_id,
            "episode_ordinal": episode_packet.ordinal,
        },
        readiness=replace(
            packet.readiness,
            claim_source_activity_count=episode_packet.claim_source_activity_count,
            activity_count=episode_packet.activity_count,
            episode_count=1,
            manifest_count=1,
        ),
        episode_packets=(episode_packet,),
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
                ActivityUnit.activity_text_status == ACTIVITY_TEXT_STATUS_COMPLETED,
                ActivityUnit.activity_text.is_not(None),
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
        activity_packets = _activity_packets(session, episode)
        source_refs = tuple(ref for activity in activity_packets for ref in activity.source_refs)
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
                included_ranges=_all_activity_ranges(activity_packets),
                omitted_ranges=(),
                origin_counts=_activity_origin_counts(activity_packets),
                claim_source_activity_count=sum(1 for activity in activity_packets if activity.source_refs),
                tool_result_text_byte_count=manifest.tool_result_text_byte_count,
                included_activities=activity_packets,
                source_refs=source_refs,
            ),
        )
    return tuple(packets)


def _activity_packets(session: Session, episode: Episode) -> tuple[ActivityPacket, ...]:
    units = list(
        session.scalars(
            select(ActivityUnit)
            .where(
                ActivityUnit.analysis_run_id == episode.analysis_run_id,
                ActivityUnit.episode_id == episode.id,
            )
            .order_by(ActivityUnit.ordinal, ActivityUnit.id),
        ),
    )
    packets: list[ActivityPacket] = []
    for index, unit in enumerate(units):
        receipt_metadata = _bounded_json(unit.receipt_json or {})
        source_metadata = _bounded_json(unit.source_metadata_json or {})
        activity_text_metadata = _bounded_json(unit.activity_text_metadata_json or {})
        source_entry_row_ids = tuple(int(value) for value in unit.source_entry_ids_json or ())
        claim_source_allowed = _activity_claim_source_allowed(unit)
        source_refs = _source_refs(
            unit=unit,
            episode=episode,
            activity_index=index,
            source_entry_row_ids=source_entry_row_ids,
            claim_source_allowed=claim_source_allowed,
            receipt_metadata=receipt_metadata,
            source_metadata=source_metadata,
        )
        packets.append(
            ActivityPacket(
                activity_unit_id=unit.id,
                episode_id=episode.id,
                episode_ordinal=episode.ordinal,
                activity_index=index,
                sequence=unit.ordinal,
                kind=unit.kind,
                source_origin=unit.source_origin,
                claim_source_allowed=claim_source_allowed,
                source_entry_row_ids=source_entry_row_ids,
                byte_start=unit.byte_start,
                byte_end=unit.byte_end,
                message_role=unit.message_role,
                tool_call_id=unit.tool_call_id,
                tool_name=unit.tool_name,
                is_error=unit.is_error,
                text_char_count=unit.text_char_count,
                result_text_byte_count=unit.result_text_byte_count,
                result_text_line_count=unit.result_text_line_count,
                activity_text=unit.activity_text,
                activity_text_kind=unit.activity_text_kind,
                activity_text_status=unit.activity_text_status,
                activity_text_metadata=activity_text_metadata,
                receipt_metadata=receipt_metadata,
                source_metadata=source_metadata,
                source_refs=source_refs,
            ),
        )
    return tuple(packets)


def _source_refs(
    *,
    unit: ActivityUnit,
    episode: Episode,
    activity_index: int,
    source_entry_row_ids: tuple[int, ...],
    claim_source_allowed: bool,
    receipt_metadata: Mapping[str, Any],
    source_metadata: Mapping[str, Any],
) -> tuple[SourceRef, ...]:
    if not claim_source_allowed or unit.activity_text is None:
        return ()

    source_ref_id = (
        f"ar{unit.analysis_run_id}:ep{episode.ordinal}:act{unit.ordinal}:"
        f"entries{','.join(str(row_id) for row_id in source_entry_row_ids) or 'none'}"
    )
    return (
        SourceRef(
            source_ref_id=source_ref_id,
            activity_unit_id=unit.id,
            episode_id=episode.id,
            episode_ordinal=episode.ordinal,
            activity_index=activity_index,
            activity_kind=unit.kind,
            source_origin=unit.source_origin,
            claim_source_allowed=claim_source_allowed,
            source_entry_row_ids=source_entry_row_ids,
            byte_start=unit.byte_start,
            byte_end=unit.byte_end,
            excerpts=(_bounded_text(unit.activity_text),),
            receipt_metadata=receipt_metadata,
            source_metadata=source_metadata,
        ),
    )


def _activity_claim_source_allowed(unit: ActivityUnit) -> bool:
    return (
        unit.source_origin in {SOURCE_ORIGIN_LOCAL, SOURCE_ORIGIN_MIXED}
        and unit.kind in CLAIM_SOURCE_ACTIVITY_KINDS
        and unit.activity_text_status == ACTIVITY_TEXT_STATUS_COMPLETED
        and unit.activity_text is not None
    )


def _activity_origin_counts(activities: tuple[ActivityPacket, ...]) -> dict[str, int]:
    counts = _empty_origin_counts()
    for activity in activities:
        key = f"{activity.source_origin}_activity_count"
        if key not in counts:
            key = f"{SOURCE_ORIGIN_UNKNOWN}_activity_count"
        counts[key] += 1
    return counts


def _all_activity_ranges(activities: tuple[ActivityPacket, ...]) -> tuple[Mapping[str, int], ...]:
    if not activities:
        return ()
    return ({"start_index": 0, "end_index": len(activities) - 1, "count": len(activities)},)


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
