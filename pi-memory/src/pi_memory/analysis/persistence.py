"""Persistence for deterministic Phase 5A transcript structure analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pi_memory.analysis.activity import NormalizedActivity, normalize_transcript_entries
from pi_memory.analysis.episodes import NormalizedEpisode, segment_activities
from pi_memory.analysis.manifests import (
    BuiltEpisodeManifest,
    BuiltSessionSnapshotShell,
    build_episode_manifests,
    build_session_snapshot_shell,
)
from pi_memory.db import (
    ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    ANALYSIS_STATUS_COMPLETED,
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
    entries = _transcript_entries(session, transcript.id)
    activities = normalize_transcript_entries(entries)
    episodes = segment_activities(activities)
    manifests = build_episode_manifests(episodes)
    snapshot_shell = build_session_snapshot_shell(episodes, manifests)

    _delete_previous_phase_5a_rows(session, transcript)

    analysis_run = _analysis_run(
        transcript=transcript,
        job_id=job_id,
        entries=entries,
        activities=activities,
        episodes=episodes,
        manifests=manifests,
        snapshot_shell=snapshot_shell,
    )
    session.add(analysis_run)
    session.flush()

    episode_rows = _persist_episodes(session, transcript, analysis_run.id, episodes)
    _persist_activity_units(session, transcript, analysis_run.id, activities, episodes, episode_rows)
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


def _transcript_entries(session: Session, transcript_id: int) -> list[TranscriptEntry]:
    return list(
        session.scalars(
            select(TranscriptEntry)
            .where(TranscriptEntry.transcript_id == transcript_id)
            .order_by(TranscriptEntry.byte_start, TranscriptEntry.id),
        ),
    )


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
) -> None:
    episode_by_activity = _episode_by_activity(episodes, episode_rows)
    for ordinal, activity in enumerate(activities):
        episode = episode_by_activity[id(activity)]
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
            ),
        )


def _episode_by_activity(
    episodes: list[NormalizedEpisode],
    episode_rows: dict[int, Episode],
) -> dict[int, Episode]:
    mapping: dict[int, Episode] = {}
    # `segment_activities` keeps the original NormalizedActivity objects in episodes.
    # Identity mapping avoids relying on non-unique byte spans or source ids.
    for episode in episodes:
        row = episode_rows[episode.ordinal]
        for activity in episode.activities:
            mapping[id(activity)] = row
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
                omitted_raw_text_bytes=manifest.omitted_raw_text_bytes,
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
