from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from pi_memory.db.base import Base
from pi_memory.db.constants import (
    ACTIVITY_TEXT_KIND_UNAVAILABLE,
    ACTIVITY_TEXT_STATUS_PENDING,
    ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    ANALYSIS_STATUS_RUNNING,
    EPISODE_STATUS_CLOSED,
    SESSION_SNAPSHOT_STATUS_READY_FOR_INTERPRETATION,
    SOURCE_ORIGIN_UNKNOWN,
)

if TYPE_CHECKING:
    from pi_memory.db.models.durable import DurableMemorySource
    from pi_memory.db.models.ingestion import (
        MemorySession,
        Transcript,
    )
    from pi_memory.db.models.interpretation import (
        EpisodeInterpretationSnapshot,
        SessionInterpretationSnapshot,
    )
    from pi_memory.db.models.jobs import Job


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

    session: Mapped[MemorySession] = relationship("MemorySession", back_populates="analysis_runs")
    transcript: Mapped[Transcript] = relationship("Transcript", back_populates="analysis_runs")
    job: Mapped[Job | None] = relationship("Job", back_populates="analysis_runs")
    activity_units: Mapped[list[ActivityUnit]] = relationship(
        "ActivityUnit",
        back_populates="analysis_run",
        cascade="all, delete-orphan",
    )
    episodes: Mapped[list[Episode]] = relationship(
        "Episode", back_populates="analysis_run", cascade="all, delete-orphan"
    )
    episode_manifests: Mapped[list[EpisodeManifest]] = relationship(
        "EpisodeManifest",
        back_populates="analysis_run",
        cascade="all, delete-orphan",
    )
    episode_interpretation_snapshots: Mapped[list[EpisodeInterpretationSnapshot]] = relationship(
        "EpisodeInterpretationSnapshot",
        back_populates="analysis_run",
        cascade="all, delete-orphan",
    )
    session_snapshot_shells: Mapped[list[SessionSnapshotShell]] = relationship(
        "SessionSnapshotShell", back_populates="analysis_run"
    )
    session_interpretation_snapshots: Mapped[list[SessionInterpretationSnapshot]] = relationship(
        "SessionInterpretationSnapshot",
        back_populates="analysis_run",
    )


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
        CheckConstraint(
            "source_origin IN ('local', 'inherited', 'mixed', 'unknown')",
            name="ck_activity_units_source_origin_valid",
        ),
        CheckConstraint(
            "activity_text_kind IN ('deterministic', 'tool_summary', 'unavailable')",
            name="ck_activity_units_activity_text_kind_valid",
        ),
        CheckConstraint(
            "activity_text_status IN ('pending', 'completed', 'skipped', 'failed')",
            name="ck_activity_units_activity_text_status_valid",
        ),
        CheckConstraint(
            "activity_text_status != 'completed' OR activity_text IS NOT NULL",
            name="ck_activity_units_completed_activity_text_present",
        ),
        Index("ix_activity_units_analysis_run_ordinal", "analysis_run_id", "ordinal"),
        Index("ix_activity_units_transcript_byte_start", "transcript_id", "byte_start"),
        Index("ix_activity_units_episode_ordinal", "episode_id", "ordinal"),
        Index("ix_activity_units_kind", "kind"),
        Index("ix_activity_units_tool_call_id", "tool_call_id"),
        Index("ix_activity_units_source_origin", "source_origin"),
        Index("ix_activity_units_analysis_run_text_status", "analysis_run_id", "activity_text_status"),
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
    source_origin: Mapped[str] = mapped_column(default=SOURCE_ORIGIN_UNKNOWN, server_default=SOURCE_ORIGIN_UNKNOWN)
    activity_text: Mapped[str | None] = mapped_column(Text)
    activity_text_kind: Mapped[str] = mapped_column(
        default=ACTIVITY_TEXT_KIND_UNAVAILABLE,
        server_default=ACTIVITY_TEXT_KIND_UNAVAILABLE,
    )
    activity_text_status: Mapped[str] = mapped_column(
        default=ACTIVITY_TEXT_STATUS_PENDING,
        server_default=ACTIVITY_TEXT_STATUS_PENDING,
    )
    activity_text_metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        server_default=text("'{}'"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    analysis_run: Mapped[AnalysisRun] = relationship("AnalysisRun", back_populates="activity_units")
    session: Mapped[MemorySession] = relationship("MemorySession", back_populates="activity_units")
    transcript: Mapped[Transcript] = relationship("Transcript", back_populates="activity_units")
    episode: Mapped[Episode | None] = relationship("Episode", back_populates="activity_units")
    durable_memory_sources: Mapped[list[DurableMemorySource]] = relationship(
        "DurableMemorySource", back_populates="activity_unit"
    )


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

    analysis_run: Mapped[AnalysisRun] = relationship("AnalysisRun", back_populates="episodes")
    session: Mapped[MemorySession] = relationship("MemorySession", back_populates="episodes")
    transcript: Mapped[Transcript] = relationship("Transcript", back_populates="episodes")
    activity_units: Mapped[list[ActivityUnit]] = relationship("ActivityUnit", back_populates="episode")
    manifest: Mapped[EpisodeManifest | None] = relationship(
        "EpisodeManifest",
        back_populates="episode",
        cascade="all, delete-orphan",
        uselist=False,
    )
    interpretation_snapshot: Mapped[EpisodeInterpretationSnapshot | None] = relationship(
        "EpisodeInterpretationSnapshot",
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
            "tool_result_text_byte_count >= 0",
            name="ck_episode_manifests_tool_result_text_byte_count_non_negative",
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
    tool_result_text_byte_count: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    analysis_run: Mapped[AnalysisRun] = relationship("AnalysisRun", back_populates="episode_manifests")
    session: Mapped[MemorySession] = relationship("MemorySession", back_populates="episode_manifests")
    transcript: Mapped[Transcript] = relationship("Transcript", back_populates="episode_manifests")
    episode: Mapped[Episode] = relationship("Episode", back_populates="manifest")


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

    session: Mapped[MemorySession] = relationship("MemorySession", back_populates="session_snapshot_shells")
    transcript: Mapped[Transcript | None] = relationship("Transcript", back_populates="session_snapshot_shells")
    analysis_run: Mapped[AnalysisRun | None] = relationship("AnalysisRun", back_populates="session_snapshot_shells")
