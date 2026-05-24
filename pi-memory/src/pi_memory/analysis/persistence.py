"""Persistence for deterministic Phase 5A transcript structure analysis."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pi_memory.analysis.activity import NormalizedActivity, normalize_transcript_entries
from pi_memory.analysis.episodes import NormalizedEpisode, segment_activities
from pi_memory.analysis.manifests import (
    BuiltEpisodeManifest,
    BuiltSessionSnapshotShell,
    ForkProvenance,
    build_episode_manifests,
    build_session_snapshot_shell,
)
from pi_memory.constants import (
    ACTIVITY_KIND_ASSISTANT_TEXT,
    ACTIVITY_KIND_ASSISTANT_THINKING,
    ACTIVITY_KIND_COMPACTION,
    ACTIVITY_KIND_CUSTOM_EVENT,
    ACTIVITY_KIND_ORPHAN_TOOL_RESULT,
    ACTIVITY_KIND_PENDING_TOOL_CALL,
    ACTIVITY_KIND_SESSION_EVENT,
    ACTIVITY_KIND_TOOL_PAIR,
    ACTIVITY_KIND_USER_TEXT,
    ACTIVITY_TEXT_KIND_DETERMINISTIC,
    ACTIVITY_TEXT_KIND_UNAVAILABLE,
    ACTIVITY_TEXT_STATUS_COMPLETED,
    ACTIVITY_TEXT_STATUS_PENDING,
    ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    ANALYSIS_STATUS_COMPLETED,
    SOURCE_ORIGIN_INHERITED,
    SOURCE_ORIGIN_LOCAL,
    SOURCE_ORIGIN_UNKNOWN,
    STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
    STRUCTURAL_LIVENESS_POLICY_VERSION,
)
from pi_memory.db.models import (
    ActivityUnit,
    AnalysisRun,
    Episode,
    EpisodeManifest,
    SessionSnapshotShell,
    Transcript,
    TranscriptEntry,
)


@dataclass(frozen=True)
class TranscriptAnalysisResult:
    """Safe summary of persisted Phase 5A transcript structure analysis."""

    analysis_run_id: int
    activity_count: int
    episode_count: int
    manifest_count: int
    snapshot_shell_id: int
    analyzed_through_entry_id: int | None
    analyzed_through_byte_offset: int
    status: str

    def to_result_json(self) -> dict[str, Any]:
        """Return a safe JSON-serializable result payload."""
        return {
            "analysis_run_id": self.analysis_run_id,
            "status": self.status,
            "activity_count": self.activity_count,
            "episode_count": self.episode_count,
            "manifest_count": self.manifest_count,
            "snapshot_shell_id": self.snapshot_shell_id,
            "analyzed_through_entry_id": self.analyzed_through_entry_id,
            "analyzed_through_byte_offset": self.analyzed_through_byte_offset,
        }


@dataclass(frozen=True)
class ActivityTextProjection:
    """Derived text projection for one activity unit."""

    text: str | None
    kind: str
    status: str
    metadata_json: dict[str, Any]


def analyze_transcript_structure(
    session: Session,
    transcript: Transcript,
    job_id: int | None = None,
) -> TranscriptAnalysisResult:
    """Rebuild and persist deterministic Phase 5A rows for a transcript.

    Args:
        session: Active SQLAlchemy session participating in the caller's
            transaction.
        transcript: Transcript to analyze. Canonical entries are queried from
            the database ordered by source byte span.
        job_id: Optional durable job id associated with this rebuild.

    Returns:
        Safe persisted analysis summary for process_transcript results.
    """
    _resolve_parent_transcript_id(session, transcript)
    entries = _transcript_entries(session, transcript.id)
    entry_source_origins = _entry_source_origins(session, transcript, entries)
    activities = normalize_transcript_entries(entries, entry_source_origins=entry_source_origins)
    episodes = segment_activities(activities)
    manifests = build_episode_manifests(episodes)
    snapshot_shell = build_session_snapshot_shell(
        episodes,
        manifests,
        ForkProvenance(
            parent_transcript_path=transcript.parent_transcript_path,
            parent_transcript_id=transcript.parent_transcript_id,
        ),
    )

    existing_result = _current_analysis_result_for_job(
        session=session,
        transcript=transcript,
        job_id=job_id,
        entries=entries,
        activities=activities,
        episodes=episodes,
        manifests=manifests,
        snapshot_shell=snapshot_shell,
    )
    if existing_result is not None:
        return existing_result

    _delete_previous_phase_5a_rows(session, transcript)

    analysis_run = _analysis_run(
        transcript=transcript,
        job_id=job_id,
        entries=entries,
        activities=activities,
        episodes=episodes,
        manifests=manifests,
        snapshot_shell=snapshot_shell,
        structural_analysis_schema_version=STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
        liveness_policy_version=STRUCTURAL_LIVENESS_POLICY_VERSION,
        parent_transcript_path=transcript.parent_transcript_path,
        parent_transcript_id=transcript.parent_transcript_id,
    )
    session.add(analysis_run)
    session.flush()

    episode_rows = _persist_episodes(session, transcript, analysis_run.id, episodes)
    _persist_activity_units(session, transcript, analysis_run.id, activities, episodes, episode_rows, entries)
    _persist_episode_manifests(session, transcript, analysis_run.id, manifests, episode_rows)
    snapshot_row = _persist_session_snapshot_shell(session, transcript, analysis_run.id, snapshot_shell)
    session.flush()

    return TranscriptAnalysisResult(
        analysis_run_id=analysis_run.id,
        activity_count=analysis_run.activity_count,
        episode_count=analysis_run.episode_count,
        manifest_count=analysis_run.manifest_count,
        snapshot_shell_id=snapshot_row.id,
        analyzed_through_entry_id=analysis_run.analyzed_through_entry_id,
        analyzed_through_byte_offset=analysis_run.analyzed_through_byte_offset,
        status=analysis_run.status,
    )


def _current_analysis_result_for_job(
    *,
    session: Session,
    transcript: Transcript,
    job_id: int | None,
    entries: list[TranscriptEntry],
    activities: list[NormalizedActivity],
    episodes: list[NormalizedEpisode],
    manifests: list[BuiltEpisodeManifest],
    snapshot_shell: BuiltSessionSnapshotShell,
) -> TranscriptAnalysisResult | None:
    if job_id is None:
        return None

    analysis_run = session.scalar(
        select(AnalysisRun)
        .where(
            AnalysisRun.transcript_id == transcript.id,
            AnalysisRun.job_id == job_id,
            AnalysisRun.analysis_kind == ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
            AnalysisRun.status == ANALYSIS_STATUS_COMPLETED,
        )
        .order_by(AnalysisRun.id.desc())
        .limit(1),
    )
    if analysis_run is None or not _analysis_run_matches(
        analysis_run=analysis_run,
        entries=entries,
        activities=activities,
        episodes=episodes,
        manifests=manifests,
        snapshot_shell=snapshot_shell,
    ):
        return None

    snapshot_row = session.scalar(
        select(SessionSnapshotShell).where(
            SessionSnapshotShell.session_id == transcript.session_id,
            SessionSnapshotShell.transcript_id == transcript.id,
            SessionSnapshotShell.analysis_run_id == analysis_run.id,
        ),
    )
    if snapshot_row is None or not _analysis_rows_complete(session, analysis_run.id, activities, episodes, manifests):
        return None

    return TranscriptAnalysisResult(
        analysis_run_id=analysis_run.id,
        activity_count=analysis_run.activity_count,
        episode_count=analysis_run.episode_count,
        manifest_count=analysis_run.manifest_count,
        snapshot_shell_id=snapshot_row.id,
        analyzed_through_entry_id=analysis_run.analyzed_through_entry_id,
        analyzed_through_byte_offset=analysis_run.analyzed_through_byte_offset,
        status=analysis_run.status,
    )


def _analysis_run_matches(
    *,
    analysis_run: AnalysisRun,
    entries: list[TranscriptEntry],
    activities: list[NormalizedActivity],
    episodes: list[NormalizedEpisode],
    manifests: list[BuiltEpisodeManifest],
    snapshot_shell: BuiltSessionSnapshotShell,
) -> bool:
    return (
        analysis_run.source_byte_start == min((entry.byte_start for entry in entries), default=None)
        and analysis_run.source_byte_end == max((entry.byte_end for entry in entries), default=None)
        and analysis_run.analyzed_through_entry_id == snapshot_shell.analyzed_through_entry_id
        and analysis_run.analyzed_through_byte_offset == snapshot_shell.analyzed_through_byte_offset
        and analysis_run.activity_count == len(activities)
        and analysis_run.episode_count == len(episodes)
        and analysis_run.manifest_count == len(manifests)
    )


def _analysis_rows_complete(
    session: Session,
    analysis_run_id: int,
    activities: list[NormalizedActivity],
    episodes: list[NormalizedEpisode],
    manifests: list[BuiltEpisodeManifest],
) -> bool:
    return (
        _analysis_row_count(session, ActivityUnit, analysis_run_id) == len(activities)
        and _analysis_row_count(session, Episode, analysis_run_id) == len(episodes)
        and _analysis_row_count(session, EpisodeManifest, analysis_run_id) == len(manifests)
    )


def _analysis_row_count(session: Session, model: type[Any], analysis_run_id: int) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(model).where(model.analysis_run_id == analysis_run_id),
        )
        or 0,
    )


def _transcript_entries(session: Session, transcript_id: int) -> list[TranscriptEntry]:
    return list(
        session.scalars(
            select(TranscriptEntry)
            .where(TranscriptEntry.transcript_id == transcript_id)
            .order_by(TranscriptEntry.byte_start, TranscriptEntry.id),
        ),
    )


def _resolve_parent_transcript_id(session: Session, transcript: Transcript) -> None:
    if transcript.parent_transcript_path is None or transcript.parent_transcript_id is not None:
        return

    parent_id = session.scalar(
        select(Transcript.id)
        .where(
            Transcript.path == transcript.parent_transcript_path,
            Transcript.id != transcript.id,
        )
        .order_by(Transcript.id)
        .limit(1),
    )
    if parent_id is None:
        return

    transcript.parent_transcript_id = parent_id
    session.flush()


def _entry_source_origins(
    session: Session,
    transcript: Transcript,
    entries: list[TranscriptEntry],
) -> dict[int, str]:
    if transcript.parent_transcript_path is None:
        return {entry.id: SOURCE_ORIGIN_LOCAL for entry in entries if entry.id is not None}

    if transcript.parent_transcript_id is None:
        return {
            entry.id: SOURCE_ORIGIN_LOCAL if entry.entry_type == "session" else SOURCE_ORIGIN_UNKNOWN
            for entry in entries
            if entry.id is not None
        }

    parent_entry_ids = set(
        session.scalars(
            select(TranscriptEntry.entry_id).where(
                TranscriptEntry.transcript_id == transcript.parent_transcript_id,
                TranscriptEntry.entry_id.is_not(None),
            ),
        ),
    )
    origins: dict[int, str] = {}
    for entry in entries:
        if entry.id is None:
            continue
        origins[entry.id] = _entry_source_origin(entry, parent_entry_ids)
    return origins


def _entry_source_origin(entry: TranscriptEntry, parent_entry_ids: set[str]) -> str:
    if entry.entry_type == "session":
        return SOURCE_ORIGIN_LOCAL
    if entry.entry_id is None:
        return SOURCE_ORIGIN_UNKNOWN
    if entry.entry_id in parent_entry_ids:
        return SOURCE_ORIGIN_INHERITED
    return SOURCE_ORIGIN_LOCAL


def _delete_previous_phase_5a_rows(session: Session, transcript: Transcript) -> None:
    # Snapshot shells are session-scoped, while analysis runs are transcript-scoped.
    # Delete shells first so run deletion cannot leave a SET NULL shell behind.
    existing_shells = session.scalars(
        select(SessionSnapshotShell).where(SessionSnapshotShell.session_id == transcript.session_id),
    )
    for shell in existing_shells:
        session.delete(shell)

    existing_runs = session.scalars(
        select(AnalysisRun).where(
            AnalysisRun.transcript_id == transcript.id,
            AnalysisRun.analysis_kind == ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
        ),
    )
    for run in existing_runs:
        session.delete(run)

    session.flush()


def _analysis_run(
    *,
    transcript: Transcript,
    job_id: int | None,
    entries: list[TranscriptEntry],
    activities: list[NormalizedActivity],
    episodes: list[NormalizedEpisode],
    manifests: list[BuiltEpisodeManifest],
    snapshot_shell: BuiltSessionSnapshotShell,
    structural_analysis_schema_version: int = STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
    liveness_policy_version: int = STRUCTURAL_LIVENESS_POLICY_VERSION,
    parent_transcript_path: str | None = None,
    parent_transcript_id: int | None = None,
) -> AnalysisRun:
    now = datetime.now(UTC)
    return AnalysisRun(
        session_id=transcript.session_id,
        transcript_id=transcript.id,
        job_id=job_id,
        analysis_kind=ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
        status=ANALYSIS_STATUS_COMPLETED,
        source_byte_start=min((entry.byte_start for entry in entries), default=None),
        source_byte_end=max((entry.byte_end for entry in entries), default=None),
        analyzed_through_entry_id=snapshot_shell.analyzed_through_entry_id,
        analyzed_through_byte_offset=snapshot_shell.analyzed_through_byte_offset,
        activity_count=len(activities),
        episode_count=len(episodes),
        manifest_count=len(manifests),
        diagnostics_json={
            "phase": "5A",
            "analysis_kind": ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
            "entry_count": len(entries),
            "structural_analysis_schema_version": structural_analysis_schema_version,
            "liveness_policy_version": liveness_policy_version,
            "parent_transcript_path": parent_transcript_path,
            "parent_transcript_id": parent_transcript_id,
        },
        finished_at=now,
    )


def _persist_episodes(
    session: Session,
    transcript: Transcript,
    analysis_run_id: int,
    episodes: list[NormalizedEpisode],
) -> dict[int, Episode]:
    rows: dict[int, Episode] = {}
    for episode in episodes:
        row = Episode(
            analysis_run_id=analysis_run_id,
            session_id=transcript.session_id,
            transcript_id=transcript.id,
            ordinal=episode.ordinal,
            status=episode.status,
            close_reason=episode.close_reason,
            first_entry_id=episode.first_entry_id,
            last_entry_id=episode.last_entry_id,
            byte_start=episode.byte_start,
            byte_end=episode.byte_end,
            timestamp_start=episode.timestamp_start,
            timestamp_end=episode.timestamp_end,
            activity_count=episode.activity_count,
            message_count=episode.message_count,
            tool_pair_count=episode.tool_pair_count,
            boundary_metadata=episode.boundary_metadata,
        )
        session.add(row)
        rows[episode.ordinal] = row
    session.flush()
    return rows


def _persist_activity_units(
    session: Session,
    transcript: Transcript,
    analysis_run_id: int,
    activities: list[NormalizedActivity],
    episodes: list[NormalizedEpisode],
    episode_rows: dict[int, Episode],
    entries: list[TranscriptEntry],
) -> None:
    episode_by_activity_sequence = _episode_by_activity_sequence(episodes, episode_rows)
    entries_by_id = {entry.id: entry for entry in entries if entry.id is not None}
    for ordinal, activity in enumerate(activities):
        episode = episode_by_activity_sequence[activity.sequence]
        activity_text = _activity_text_projection(activity, entries_by_id)
        session.add(
            ActivityUnit(
                analysis_run_id=analysis_run_id,
                session_id=transcript.session_id,
                transcript_id=transcript.id,
                episode_id=episode.id,
                ordinal=ordinal,
                kind=activity.kind,
                first_entry_id=_first_source_entry_id(activity),
                last_entry_id=_last_source_entry_id(activity),
                source_entry_ids_json=list(activity.source_entry_ids),
                byte_start=activity.byte_start,
                byte_end=activity.byte_end,
                timestamp_start=activity.timestamp_start,
                timestamp_end=activity.timestamp_end,
                message_role=activity.message_role,
                tool_call_id=activity.tool_call_id,
                tool_name=activity.tool_name,
                is_error=activity.is_error,
                raw_text_available=activity.raw_text_available,
                text_char_count=activity.text_char_count,
                result_text_byte_count=activity.result_text_byte_count,
                result_text_line_count=activity.result_text_line_count,
                receipt_json=activity.receipt_json,
                source_metadata_json=activity.source_metadata_json,
                source_origin=activity.source_origin,
                activity_text=activity_text.text,
                activity_text_kind=activity_text.kind,
                activity_text_status=activity_text.status,
                activity_text_metadata_json=activity_text.metadata_json,
            ),
        )


def _activity_text_projection(
    activity: NormalizedActivity,
    entries_by_id: Mapping[int, TranscriptEntry],
) -> ActivityTextProjection:
    if activity.kind == ACTIVITY_KIND_TOOL_PAIR:
        return ActivityTextProjection(
            text=None,
            kind=ACTIVITY_TEXT_KIND_UNAVAILABLE,
            status=ACTIVITY_TEXT_STATUS_PENDING,
            metadata_json={
                "version": 1,
                "producer": "tool_activity_summarizer",
                "reason": "awaiting_tool_summary",
                "source_entry_ids": list(activity.source_entry_ids),
            },
        )

    text = _deterministic_activity_text(activity, entries_by_id)
    return ActivityTextProjection(
        text=text,
        kind=ACTIVITY_TEXT_KIND_DETERMINISTIC,
        status=ACTIVITY_TEXT_STATUS_COMPLETED,
        metadata_json={
            "version": 1,
            "producer": "phase_5a_deterministic",
            "activity_kind": activity.kind,
            "source_entry_ids": list(activity.source_entry_ids),
            "text_char_count": len(text),
        },
    )


def _deterministic_activity_text(
    activity: NormalizedActivity,
    entries_by_id: Mapping[int, TranscriptEntry],
) -> str:
    if activity.kind == ACTIVITY_KIND_USER_TEXT:
        return _message_activity_text("User message", activity, entries_by_id)
    if activity.kind == ACTIVITY_KIND_ASSISTANT_TEXT:
        return _message_activity_text("Assistant message", activity, entries_by_id)
    if activity.kind == ACTIVITY_KIND_ASSISTANT_THINKING:
        return _message_activity_text("Assistant thinking", activity, entries_by_id)
    if activity.kind == ACTIVITY_KIND_COMPACTION:
        return _compaction_activity_text(activity)
    if activity.kind == ACTIVITY_KIND_SESSION_EVENT:
        return _event_activity_text("Session event", activity)
    if activity.kind == ACTIVITY_KIND_CUSTOM_EVENT:
        return _custom_event_activity_text(activity)
    if activity.kind == ACTIVITY_KIND_PENDING_TOOL_CALL:
        return _pending_tool_call_activity_text(activity)
    if activity.kind == ACTIVITY_KIND_ORPHAN_TOOL_RESULT:
        return _orphan_tool_result_activity_text(activity)
    return _event_activity_text("Activity", activity)


def _message_activity_text(
    label: str,
    activity: NormalizedActivity,
    entries_by_id: Mapping[int, TranscriptEntry],
) -> str:
    entry = _first_activity_entry(activity, entries_by_id)
    body = _message_text(entry, _content_index(activity.source_metadata_json)) if entry is not None else ""
    return _prefixed_text(label, body)


def _compaction_activity_text(activity: NormalizedActivity) -> str:
    metadata = activity.source_metadata_json
    summary = _preview_value(metadata.get("summary"))
    if summary is not None:
        return _prefixed_text("Compaction summary", summary)

    details = [f"{key}={metadata[key]}" for key in ("firstKeptEntryId", "tokensBefore") if key in metadata]
    suffix = "; ".join(details) if details else "no summary text"
    return f"Compaction event: {suffix}."


def _custom_event_activity_text(activity: NormalizedActivity) -> str:
    metadata = activity.source_metadata_json
    if metadata.get("entry_type") == "branch_summary":
        summary = _preview_value(metadata.get("summary"))
        if summary is not None:
            return _prefixed_text("Branch summary", summary)
    return _event_activity_text("Custom event", activity)


def _event_activity_text(label: str, activity: NormalizedActivity) -> str:
    metadata = activity.source_metadata_json
    entry_type = metadata.get("entry_type") or activity.kind
    fields = _string_list(metadata.get("payload_keys"))
    if fields:
        return f"{label}: {entry_type}; fields: {', '.join(fields)}."
    return f"{label}: {entry_type}."


def _pending_tool_call_activity_text(activity: NormalizedActivity) -> str:
    receipt = activity.receipt_json
    tool_name = receipt.get("tool_name") or activity.tool_name or "unknown tool"
    argument_keys = _string_list(receipt.get("argument_keys"))
    if argument_keys:
        return f"Pending tool call: {tool_name}; argument keys: {', '.join(argument_keys)}; result not observed."
    return f"Pending tool call: {tool_name}; result not observed."


def _orphan_tool_result_activity_text(activity: NormalizedActivity) -> str:
    receipt = activity.receipt_json
    tool_name = receipt.get("tool_name") or activity.tool_name or "unknown tool"
    status = receipt.get("result_status") or "unknown"
    byte_count = receipt.get("result_text_byte_count") or activity.result_text_byte_count
    line_count = receipt.get("result_text_line_count") or activity.result_text_line_count
    return f"Orphan tool result: {tool_name}; status={status}; output={byte_count} bytes over {line_count} lines."


def _first_activity_entry(
    activity: NormalizedActivity,
    entries_by_id: Mapping[int, TranscriptEntry],
) -> TranscriptEntry | None:
    for entry_id in activity.source_entry_ids:
        entry = entries_by_id.get(entry_id)
        if entry is not None:
            return entry
    return None


def _message_text(entry: TranscriptEntry, content_index: int | None) -> str:
    payload = _entry_payload(entry)
    message = payload.get("message") if payload is not None else None
    if not isinstance(message, Mapping):
        return ""

    content = message.get("content")
    if content_index is not None and isinstance(content, list) and 0 <= content_index < len(content):
        return _block_text(content[content_index])
    return "\n".join(fragment for fragment in _content_text_fragments(content) if fragment)


def _entry_payload(entry: TranscriptEntry) -> dict[str, Any] | None:
    try:
        payload = json.loads(entry.raw_line)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _content_text_fragments(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [_block_text(item) for item in value]
    if isinstance(value, dict):
        text = _block_text(value)
        return [text] if text else []
    return []


def _block_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    if not isinstance(block, Mapping):
        return ""
    for key in ("text", "thinking", "content"):
        value = block.get(key)
        if isinstance(value, str):
            return value
    return ""


def _content_index(metadata: Mapping[str, Any]) -> int | None:
    value = metadata.get("content_index")
    return value if isinstance(value, int) else None


def _preview_value(value: Any) -> str | None:
    if isinstance(value, Mapping):
        preview = value.get("preview")
        if isinstance(preview, str):
            return preview
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, str)]


def _prefixed_text(label: str, body: str) -> str:
    return f"{label}:\n{body}" if body.strip() else f"{label}: (no text content)"


def _episode_by_activity_sequence(
    episodes: list[NormalizedEpisode],
    episode_rows: dict[int, Episode],
) -> dict[int, Episode]:
    mapping: dict[int, Episode] = {}
    for episode in episodes:
        row = episode_rows[episode.ordinal]
        for activity in episode.activities:
            mapping[activity.sequence] = row
    return mapping


def _persist_episode_manifests(
    session: Session,
    transcript: Transcript,
    analysis_run_id: int,
    manifests: list[BuiltEpisodeManifest],
    episode_rows: dict[int, Episode],
) -> None:
    for manifest in manifests:
        session.add(
            EpisodeManifest(
                analysis_run_id=analysis_run_id,
                session_id=transcript.session_id,
                transcript_id=transcript.id,
                episode_id=episode_rows[manifest.episode_ordinal].id,
                manifest_version=manifest.manifest_version,
                activity_count=manifest.activity_count,
                tool_pair_count=manifest.tool_pair_count,
                first_entry_id=manifest.first_entry_id,
                last_entry_id=manifest.last_entry_id,
                byte_start=manifest.byte_start,
                byte_end=manifest.byte_end,
                activity_map_json=manifest.activity_map_json,
                source_spans_json=manifest.source_spans_json,
                tool_result_text_byte_count=manifest.tool_result_text_byte_count,
            ),
        )


def _persist_session_snapshot_shell(
    session: Session,
    transcript: Transcript,
    analysis_run_id: int,
    snapshot_shell: BuiltSessionSnapshotShell,
) -> SessionSnapshotShell:
    row = SessionSnapshotShell(
        session_id=transcript.session_id,
        transcript_id=transcript.id,
        analysis_run_id=analysis_run_id,
        status=snapshot_shell.status,
        analyzed_through_entry_id=snapshot_shell.analyzed_through_entry_id,
        analyzed_through_byte_offset=snapshot_shell.analyzed_through_byte_offset,
        activity_count=snapshot_shell.activity_count,
        episode_count=snapshot_shell.episode_count,
        manifest_count=snapshot_shell.manifest_count,
        tool_pair_count=snapshot_shell.tool_pair_count,
        snapshot_json=snapshot_shell.snapshot_json,
    )
    session.add(row)
    return row


def _first_source_entry_id(activity: NormalizedActivity) -> int | None:
    if not activity.source_entry_ids:
        return None
    return activity.source_entry_ids[0]


def _last_source_entry_id(activity: NormalizedActivity) -> int | None:
    if not activity.source_entry_ids:
        return None
    return activity.source_entry_ids[-1]
