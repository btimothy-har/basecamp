"""SQLAlchemy schema for pi-memory."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for pi-memory ORM models."""


JOB_KIND_PROCESS_TRANSCRIPT = "process_transcript"

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_CLAIMED = "claimed"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_CANCELLED = "cancelled"
JOB_STATUSES = (
    JOB_STATUS_QUEUED,
    JOB_STATUS_CLAIMED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_CANCELLED,
)

ANALYSIS_KIND_TRANSCRIPT_STRUCTURE = "transcript_structure"
ANALYSIS_STATUS_RUNNING = "running"
ANALYSIS_STATUS_COMPLETED = "completed"
ANALYSIS_STATUS_FAILED = "failed"
ANALYSIS_STATUS_CANCELLED = "cancelled"
ANALYSIS_STATUSES = (
    ANALYSIS_STATUS_RUNNING,
    ANALYSIS_STATUS_COMPLETED,
    ANALYSIS_STATUS_FAILED,
    ANALYSIS_STATUS_CANCELLED,
)

ACTIVITY_KIND_USER_TEXT = "user_text"
ACTIVITY_KIND_ASSISTANT_TEXT = "assistant_text"
ACTIVITY_KIND_ASSISTANT_THINKING = "assistant_thinking"
ACTIVITY_KIND_TOOL_PAIR = "tool_pair"
ACTIVITY_KIND_PENDING_TOOL_CALL = "pending_tool_call"
ACTIVITY_KIND_ORPHAN_TOOL_RESULT = "orphan_tool_result"
ACTIVITY_KIND_COMPACTION = "compaction"
ACTIVITY_KIND_SESSION_EVENT = "session_event"
ACTIVITY_KIND_CUSTOM_EVENT = "custom_event"
ACTIVITY_KINDS = (
    ACTIVITY_KIND_USER_TEXT,
    ACTIVITY_KIND_ASSISTANT_TEXT,
    ACTIVITY_KIND_ASSISTANT_THINKING,
    ACTIVITY_KIND_TOOL_PAIR,
    ACTIVITY_KIND_PENDING_TOOL_CALL,
    ACTIVITY_KIND_ORPHAN_TOOL_RESULT,
    ACTIVITY_KIND_COMPACTION,
    ACTIVITY_KIND_SESSION_EVENT,
    ACTIVITY_KIND_CUSTOM_EVENT,
)

EPISODE_STATUS_OPEN = "open"
EPISODE_STATUS_CLOSED = "closed"
EPISODE_STATUSES = (EPISODE_STATUS_OPEN, EPISODE_STATUS_CLOSED)

EPISODE_CLOSE_REASON_COMPACTION = "compaction"
EPISODE_CLOSE_REASON_TIME_GAP = "time_gap"
EPISODE_CLOSE_REASON_TRANSCRIPT_END = "transcript_end"
EPISODE_CLOSE_REASON_CURRENT_CURSOR = "current_cursor"
EPISODE_CLOSE_REASONS = (
    EPISODE_CLOSE_REASON_COMPACTION,
    EPISODE_CLOSE_REASON_TIME_GAP,
    EPISODE_CLOSE_REASON_TRANSCRIPT_END,
    EPISODE_CLOSE_REASON_CURRENT_CURSOR,
)

SESSION_SNAPSHOT_STATUS_READY_FOR_INTERPRETATION = "ready_for_interpretation"
SESSION_SNAPSHOT_STATUSES = (SESSION_SNAPSHOT_STATUS_READY_FOR_INTERPRETATION,)


class Job(Base):
    """Durable SQLite-backed work queue job."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'claimed', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_jobs_status_valid",
        ),
        CheckConstraint("attempts >= 0", name="ck_jobs_attempts_non_negative"),
        CheckConstraint("max_attempts > 0", name="ck_jobs_max_attempts_positive"),
        CheckConstraint("attempts <= max_attempts", name="ck_jobs_attempts_within_max"),
        CheckConstraint("priority >= 0", name="ck_jobs_priority_non_negative"),
        CheckConstraint("length(kind) > 0", name="ck_jobs_kind_non_empty"),
        Index("ix_jobs_queue_claim", "status", "due_at", "priority", "created_at"),
        Index("ix_jobs_status_updated", "status", "updated_at"),
        Index("ix_jobs_kind_status", "kind", "status"),
        Index("ix_jobs_run_id", "run_id"),
        Index("ix_jobs_status_lease_expires", "status", "lease_expires_at"),
        Index("ix_jobs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]
    status: Mapped[str] = mapped_column(default=JOB_STATUS_QUEUED, server_default=JOB_STATUS_QUEUED)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    priority: Mapped[int] = mapped_column(default=0, server_default="0")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(default=3, server_default="3")
    run_id: Mapped[str | None]
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    running_pid: Mapped[int | None]
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_code: Mapped[int | None]
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    analysis_runs: Mapped[list[AnalysisRun]] = relationship(back_populates="job")


class MemorySession(Base):
    """Stable Pi session identity and optional request-provided metadata."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(unique=True, index=True)
    cwd: Mapped[str | None]
    repo_name: Mapped[str | None]
    repo_root: Mapped[str | None]
    worktree_label: Mapped[str | None]
    worktree_path: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    transcripts: Mapped[list[Transcript]] = relationship(back_populates="session", cascade="all, delete-orphan")
    observations: Mapped[list[Observation]] = relationship(back_populates="session", cascade="all, delete-orphan")
    analysis_runs: Mapped[list[AnalysisRun]] = relationship(back_populates="session", cascade="all, delete-orphan")
    activity_units: Mapped[list[ActivityUnit]] = relationship(back_populates="session", cascade="all, delete-orphan")
    episodes: Mapped[list[Episode]] = relationship(back_populates="session", cascade="all, delete-orphan")
    episode_manifests: Mapped[list[EpisodeManifest]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    session_snapshot_shells: Mapped[list[SessionSnapshotShell]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )


class Transcript(Base):
    """Transcript file cursor state for a Pi session."""

    __tablename__ = "transcripts"
    __table_args__ = (
        UniqueConstraint("session_id", "path", name="uq_transcripts_session_path"),
        Index("ix_transcripts_session_cursor", "session_id", "cursor_offset"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    path: Mapped[str]
    cursor_offset: Mapped[int] = mapped_column(default=0, server_default="0")
    file_size: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    session: Mapped[MemorySession] = relationship(back_populates="transcripts")
    observations: Mapped[list[Observation]] = relationship(back_populates="transcript")
    entries: Mapped[list[TranscriptEntry]] = relationship(back_populates="transcript", cascade="all, delete-orphan")
    analysis_runs: Mapped[list[AnalysisRun]] = relationship(back_populates="transcript", cascade="all, delete-orphan")
    activity_units: Mapped[list[ActivityUnit]] = relationship(back_populates="transcript", cascade="all, delete-orphan")
    episodes: Mapped[list[Episode]] = relationship(back_populates="transcript", cascade="all, delete-orphan")
    episode_manifests: Mapped[list[EpisodeManifest]] = relationship(
        back_populates="transcript",
        cascade="all, delete-orphan",
    )
    session_snapshot_shells: Mapped[list[SessionSnapshotShell]] = relationship(back_populates="transcript")


class Observation(Base):
    """Audit record for an observation request against a session transcript."""

    __tablename__ = "observations"
    __table_args__ = (Index("ix_observations_session_observed", "session_id", "observed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    transcript_id: Mapped[int | None] = mapped_column(ForeignKey("transcripts.id", ondelete="SET NULL"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    request_id: Mapped[str | None] = mapped_column(index=True)
    request_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    session: Mapped[MemorySession] = relationship(back_populates="observations")
    transcript: Mapped[Transcript | None] = relationship(back_populates="observations")


class TranscriptEntry(Base):
    """Raw Pi transcript line plus parsed Pi metadata."""

    __tablename__ = "transcript_entries"
    __table_args__ = (
        UniqueConstraint("transcript_id", "entry_id", name="uq_transcript_entries_entry_id"),
        UniqueConstraint("transcript_id", "byte_start", "byte_end", name="uq_transcript_entries_byte_span"),
        CheckConstraint("byte_start >= 0", name="ck_transcript_entries_byte_start_non_negative"),
        CheckConstraint("byte_end > byte_start", name="ck_transcript_entries_byte_end_after_start"),
        Index("ix_transcript_entries_transcript_byte_start", "transcript_id", "byte_start"),
        Index("ix_transcript_entries_transcript_type", "transcript_id", "entry_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"), index=True)
    entry_id: Mapped[str | None] = mapped_column(index=True)
    parent_id: Mapped[str | None] = mapped_column(index=True)
    entry_type: Mapped[str]
    message_role: Mapped[str | None]
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_line: Mapped[str] = mapped_column(Text)
    byte_start: Mapped[int]
    byte_end: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    transcript: Mapped[Transcript] = relationship(back_populates="entries")


class AnalysisRun(Base):
    """Deterministic structural analysis pass over a transcript."""

    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'cancelled')",
            name="ck_analysis_runs_status_valid",
        ),
        CheckConstraint("length(analysis_kind) > 0", name="ck_analysis_runs_kind_non_empty"),
        CheckConstraint(
            "source_byte_start IS NULL OR source_byte_start >= 0",
            name="ck_analysis_runs_source_byte_start_non_negative",
        ),
        CheckConstraint(
            "source_byte_end IS NULL OR source_byte_end >= 0",
            name="ck_analysis_runs_source_byte_end_non_negative",
        ),
        CheckConstraint(
            "source_byte_start IS NULL OR source_byte_end IS NULL OR source_byte_end > source_byte_start",
            name="ck_analysis_runs_source_span_valid",
        ),
        CheckConstraint("analyzed_through_byte_offset >= 0", name="ck_analysis_runs_byte_offset_non_negative"),
        CheckConstraint("activity_count >= 0", name="ck_analysis_runs_activity_count_non_negative"),
        CheckConstraint("episode_count >= 0", name="ck_analysis_runs_episode_count_non_negative"),
        CheckConstraint("manifest_count >= 0", name="ck_analysis_runs_manifest_count_non_negative"),
        Index("ix_analysis_runs_session_status", "session_id", "status"),
        Index("ix_analysis_runs_transcript_status", "transcript_id", "status"),
        Index("ix_analysis_runs_job_id", "job_id"),
        Index("ix_analysis_runs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    analysis_kind: Mapped[str] = mapped_column(
        default=ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
        server_default=ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    )
    status: Mapped[str] = mapped_column(default=ANALYSIS_STATUS_RUNNING, server_default=ANALYSIS_STATUS_RUNNING)
    source_byte_start: Mapped[int | None]
    source_byte_end: Mapped[int | None]
    analyzed_through_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("transcript_entries.id", ondelete="SET NULL"),
        index=True,
    )
    analyzed_through_byte_offset: Mapped[int] = mapped_column(default=0, server_default="0")
    activity_count: Mapped[int] = mapped_column(default=0, server_default="0")
    episode_count: Mapped[int] = mapped_column(default=0, server_default="0")
    manifest_count: Mapped[int] = mapped_column(default=0, server_default="0")
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    session: Mapped[MemorySession] = relationship(back_populates="analysis_runs")
    transcript: Mapped[Transcript] = relationship(back_populates="analysis_runs")
    job: Mapped[Job | None] = relationship(back_populates="analysis_runs")
    activity_units: Mapped[list[ActivityUnit]] = relationship(
        back_populates="analysis_run",
        cascade="all, delete-orphan",
    )
    episodes: Mapped[list[Episode]] = relationship(back_populates="analysis_run", cascade="all, delete-orphan")
    episode_manifests: Mapped[list[EpisodeManifest]] = relationship(
        back_populates="analysis_run",
        cascade="all, delete-orphan",
    )
    session_snapshot_shells: Mapped[list[SessionSnapshotShell]] = relationship(back_populates="analysis_run")


class ActivityUnit(Base):
    """Deterministic activity span derived from transcript entries."""

    __tablename__ = "activity_units"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "ordinal", name="uq_activity_units_analysis_run_ordinal"),
        CheckConstraint(
            "kind IN ('user_text', 'assistant_text', 'assistant_thinking', 'tool_pair', "
            "'pending_tool_call', 'orphan_tool_result', 'compaction', 'session_event', 'custom_event')",
            name="ck_activity_units_kind_valid",
        ),
        CheckConstraint("ordinal >= 0", name="ck_activity_units_ordinal_non_negative"),
        CheckConstraint("byte_start >= 0", name="ck_activity_units_byte_start_non_negative"),
        CheckConstraint("byte_end > byte_start", name="ck_activity_units_byte_end_after_start"),
        CheckConstraint("text_char_count >= 0", name="ck_activity_units_text_char_count_non_negative"),
        CheckConstraint("result_text_byte_count >= 0", name="ck_activity_units_result_text_byte_count_non_negative"),
        CheckConstraint("result_text_line_count >= 0", name="ck_activity_units_result_text_line_count_non_negative"),
        Index("ix_activity_units_analysis_run_ordinal", "analysis_run_id", "ordinal"),
        Index("ix_activity_units_transcript_byte_start", "transcript_id", "byte_start"),
        Index("ix_activity_units_episode_ordinal", "episode_id", "ordinal"),
        Index("ix_activity_units_kind", "kind"),
        Index("ix_activity_units_tool_call_id", "tool_call_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("episodes.id", ondelete="SET NULL"), index=True)
    ordinal: Mapped[int]
    kind: Mapped[str]
    first_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("transcript_entries.id", ondelete="SET NULL"),
        index=True,
    )
    last_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("transcript_entries.id", ondelete="SET NULL"),
        index=True,
    )
    source_entry_ids_json: Mapped[list[int]] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    byte_start: Mapped[int]
    byte_end: Mapped[int]
    timestamp_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timestamp_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_role: Mapped[str | None]
    tool_call_id: Mapped[str | None]
    tool_name: Mapped[str | None]
    is_error: Mapped[bool | None] = mapped_column(Boolean)
    raw_text_available: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    text_char_count: Mapped[int] = mapped_column(default=0, server_default="0")
    result_text_byte_count: Mapped[int] = mapped_column(default=0, server_default="0")
    result_text_line_count: Mapped[int] = mapped_column(default=0, server_default="0")
    receipt_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    source_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    analysis_run: Mapped[AnalysisRun] = relationship(back_populates="activity_units")
    session: Mapped[MemorySession] = relationship(back_populates="activity_units")
    transcript: Mapped[Transcript] = relationship(back_populates="activity_units")
    episode: Mapped[Episode | None] = relationship(back_populates="activity_units")


class Episode(Base):
    """Deterministic episode boundary over activity units."""

    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "ordinal", name="uq_episodes_analysis_run_ordinal"),
        CheckConstraint("status IN ('open', 'closed')", name="ck_episodes_status_valid"),
        CheckConstraint(
            "close_reason IS NULL OR close_reason IN ('compaction', 'time_gap', 'transcript_end', 'current_cursor')",
            name="ck_episodes_close_reason_valid",
        ),
        CheckConstraint("status = 'open' OR close_reason IS NOT NULL", name="ck_episodes_closed_requires_reason"),
        CheckConstraint("ordinal >= 0", name="ck_episodes_ordinal_non_negative"),
        CheckConstraint("byte_start >= 0", name="ck_episodes_byte_start_non_negative"),
        CheckConstraint("byte_end > byte_start", name="ck_episodes_byte_end_after_start"),
        CheckConstraint("activity_count >= 0", name="ck_episodes_activity_count_non_negative"),
        CheckConstraint("message_count >= 0", name="ck_episodes_message_count_non_negative"),
        CheckConstraint("tool_pair_count >= 0", name="ck_episodes_tool_pair_count_non_negative"),
        Index("ix_episodes_analysis_run_ordinal", "analysis_run_id", "ordinal"),
        Index("ix_episodes_transcript_byte_start", "transcript_id", "byte_start"),
        Index("ix_episodes_close_reason", "close_reason"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int]
    status: Mapped[str] = mapped_column(default=EPISODE_STATUS_CLOSED, server_default=EPISODE_STATUS_CLOSED)
    close_reason: Mapped[str | None]
    first_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("transcript_entries.id", ondelete="SET NULL"),
        index=True,
    )
    last_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("transcript_entries.id", ondelete="SET NULL"),
        index=True,
    )
    byte_start: Mapped[int]
    byte_end: Mapped[int]
    timestamp_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timestamp_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activity_count: Mapped[int] = mapped_column(default=0, server_default="0")
    message_count: Mapped[int] = mapped_column(default=0, server_default="0")
    tool_pair_count: Mapped[int] = mapped_column(default=0, server_default="0")
    boundary_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    analysis_run: Mapped[AnalysisRun] = relationship(back_populates="episodes")
    session: Mapped[MemorySession] = relationship(back_populates="episodes")
    transcript: Mapped[Transcript] = relationship(back_populates="episodes")
    activity_units: Mapped[list[ActivityUnit]] = relationship(back_populates="episode")
    manifest: Mapped[EpisodeManifest | None] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan",
        uselist=False,
    )


class EpisodeManifest(Base):
    """Rebuildable manifest of deterministic episode source spans."""

    __tablename__ = "episode_manifests"
    __table_args__ = (
        CheckConstraint("manifest_version > 0", name="ck_episode_manifests_version_positive"),
        CheckConstraint("activity_count >= 0", name="ck_episode_manifests_activity_count_non_negative"),
        CheckConstraint("tool_pair_count >= 0", name="ck_episode_manifests_tool_pair_count_non_negative"),
        CheckConstraint("byte_start >= 0", name="ck_episode_manifests_byte_start_non_negative"),
        CheckConstraint("byte_end > byte_start", name="ck_episode_manifests_byte_end_after_start"),
        CheckConstraint(
            "omitted_raw_text_bytes >= 0",
            name="ck_episode_manifests_omitted_raw_text_bytes_non_negative",
        ),
        Index("ix_episode_manifests_analysis_run_id", "analysis_run_id"),
        Index("ix_episode_manifests_transcript_byte_start", "transcript_id", "byte_start"),
        Index("ix_episode_manifests_episode_id", "episode_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), unique=True)
    manifest_version: Mapped[int] = mapped_column(default=1, server_default="1")
    activity_count: Mapped[int] = mapped_column(default=0, server_default="0")
    tool_pair_count: Mapped[int] = mapped_column(default=0, server_default="0")
    first_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("transcript_entries.id", ondelete="SET NULL"),
        index=True,
    )
    last_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("transcript_entries.id", ondelete="SET NULL"),
        index=True,
    )
    byte_start: Mapped[int]
    byte_end: Mapped[int]
    activity_map_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    source_spans_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    omitted_raw_text_bytes: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    analysis_run: Mapped[AnalysisRun] = relationship(back_populates="episode_manifests")
    session: Mapped[MemorySession] = relationship(back_populates="episode_manifests")
    transcript: Mapped[Transcript] = relationship(back_populates="episode_manifests")
    episode: Mapped[Episode] = relationship(back_populates="manifest")


class SessionSnapshotShell(Base):
    """Deterministic session snapshot shell awaiting interpretation."""

    __tablename__ = "session_snapshot_shells"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ready_for_interpretation')",
            name="ck_session_snapshot_shells_status_valid",
        ),
        CheckConstraint(
            "analyzed_through_byte_offset >= 0",
            name="ck_session_snapshot_shells_byte_offset_non_negative",
        ),
        CheckConstraint("activity_count >= 0", name="ck_session_snapshot_shells_activity_count_non_negative"),
        CheckConstraint("episode_count >= 0", name="ck_session_snapshot_shells_episode_count_non_negative"),
        CheckConstraint("manifest_count >= 0", name="ck_session_snapshot_shells_manifest_count_non_negative"),
        CheckConstraint("tool_pair_count >= 0", name="ck_session_snapshot_shells_tool_pair_count_non_negative"),
        Index("ix_session_snapshot_shells_status_updated_at", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), unique=True, index=True)
    transcript_id: Mapped[int | None] = mapped_column(ForeignKey("transcripts.id", ondelete="SET NULL"), index=True)
    analysis_run_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_runs.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(
        default=SESSION_SNAPSHOT_STATUS_READY_FOR_INTERPRETATION,
        server_default=SESSION_SNAPSHOT_STATUS_READY_FOR_INTERPRETATION,
    )
    analyzed_through_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("transcript_entries.id", ondelete="SET NULL"),
        index=True,
    )
    analyzed_through_byte_offset: Mapped[int] = mapped_column(default=0, server_default="0")
    activity_count: Mapped[int] = mapped_column(default=0, server_default="0")
    episode_count: Mapped[int] = mapped_column(default=0, server_default="0")
    manifest_count: Mapped[int] = mapped_column(default=0, server_default="0")
    tool_pair_count: Mapped[int] = mapped_column(default=0, server_default="0")
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    session: Mapped[MemorySession] = relationship(back_populates="session_snapshot_shells")
    transcript: Mapped[Transcript | None] = relationship(back_populates="session_snapshot_shells")
    analysis_run: Mapped[AnalysisRun | None] = relationship(back_populates="session_snapshot_shells")
