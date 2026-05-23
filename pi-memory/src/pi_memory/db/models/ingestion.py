from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from pi_memory.db.base import Base

if TYPE_CHECKING:
    from pi_memory.db.models.analysis import (
        ActivityUnit,
        AnalysisRun,
        Episode,
        EpisodeManifest,
        SessionSnapshotShell,
    )
    from pi_memory.db.models.durable import DurableMemoryItem
    from pi_memory.db.models.interpretation import (
        EpisodeInterpretationSnapshot,
        SessionInterpretationSnapshot,
    )


class MemorySession(Base):
    """Stable Pi session identity and optional location metadata."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(unique=True, index=True)
    cwd: Mapped[str | None]
    worktree_label: Mapped[str | None]
    worktree_path: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    transcripts: Mapped[list[Transcript]] = relationship(
        "Transcript", back_populates="session", cascade="all, delete-orphan"
    )
    observations: Mapped[list[Observation]] = relationship(
        "Observation", back_populates="session", cascade="all, delete-orphan"
    )
    analysis_runs: Mapped[list[AnalysisRun]] = relationship(
        "AnalysisRun", back_populates="session", cascade="all, delete-orphan"
    )
    activity_units: Mapped[list[ActivityUnit]] = relationship(
        "ActivityUnit", back_populates="session", cascade="all, delete-orphan"
    )
    episodes: Mapped[list[Episode]] = relationship("Episode", back_populates="session", cascade="all, delete-orphan")
    episode_manifests: Mapped[list[EpisodeManifest]] = relationship(
        "EpisodeManifest",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    episode_interpretation_snapshots: Mapped[list[EpisodeInterpretationSnapshot]] = relationship(
        "EpisodeInterpretationSnapshot",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    session_snapshot_shells: Mapped[list[SessionSnapshotShell]] = relationship(
        "SessionSnapshotShell",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    session_interpretation_snapshot: Mapped[SessionInterpretationSnapshot | None] = relationship(
        "SessionInterpretationSnapshot",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    durable_memory_items: Mapped[list[DurableMemoryItem]] = relationship(
        "DurableMemoryItem",
        back_populates="session",
        cascade="all, delete-orphan",
    )


class Transcript(Base):
    """Transcript file cursor state for a Pi session."""

    __tablename__ = "transcripts"
    __table_args__ = (
        UniqueConstraint("session_id", "path", name="uq_transcripts_session_path"),
        CheckConstraint(
            "parent_transcript_id IS NULL OR parent_transcript_id != id",
            name="ck_transcripts_parent_not_self",
        ),
        CheckConstraint(
            "parent_transcript_id IS NULL OR parent_transcript_path IS NOT NULL",
            name="ck_transcripts_parent_id_requires_path",
        ),
        CheckConstraint(
            "parent_transcript_path IS NULL OR length(parent_transcript_path) > 0",
            name="ck_transcripts_parent_path_non_empty",
        ),
        Index("ix_transcripts_session_cursor", "session_id", "cursor_offset"),
        Index("ix_transcripts_parent_transcript_id", "parent_transcript_id"),
        Index("ix_transcripts_parent_transcript_path", "parent_transcript_path"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    path: Mapped[str]
    parent_transcript_path: Mapped[str | None]
    parent_transcript_id: Mapped[int | None] = mapped_column(ForeignKey("transcripts.id", ondelete="SET NULL"))
    cursor_offset: Mapped[int] = mapped_column(default=0, server_default="0")
    file_size: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    session: Mapped[MemorySession] = relationship("MemorySession", back_populates="transcripts")
    parent_transcript: Mapped[Transcript | None] = relationship(
        "Transcript",
        back_populates="child_transcripts",
        remote_side=[id],
    )
    child_transcripts: Mapped[list[Transcript]] = relationship("Transcript", back_populates="parent_transcript")
    observations: Mapped[list[Observation]] = relationship("Observation", back_populates="transcript")
    entries: Mapped[list[TranscriptEntry]] = relationship(
        "TranscriptEntry", back_populates="transcript", cascade="all, delete-orphan"
    )
    analysis_runs: Mapped[list[AnalysisRun]] = relationship(
        "AnalysisRun", back_populates="transcript", cascade="all, delete-orphan"
    )
    activity_units: Mapped[list[ActivityUnit]] = relationship(
        "ActivityUnit", back_populates="transcript", cascade="all, delete-orphan"
    )
    episodes: Mapped[list[Episode]] = relationship("Episode", back_populates="transcript", cascade="all, delete-orphan")
    episode_manifests: Mapped[list[EpisodeManifest]] = relationship(
        "EpisodeManifest",
        back_populates="transcript",
        cascade="all, delete-orphan",
    )
    episode_interpretation_snapshots: Mapped[list[EpisodeInterpretationSnapshot]] = relationship(
        "EpisodeInterpretationSnapshot",
        back_populates="transcript",
        cascade="all, delete-orphan",
    )
    session_snapshot_shells: Mapped[list[SessionSnapshotShell]] = relationship(
        "SessionSnapshotShell", back_populates="transcript"
    )
    session_interpretation_snapshots: Mapped[list[SessionInterpretationSnapshot]] = relationship(
        "SessionInterpretationSnapshot",
        back_populates="transcript",
    )
    durable_memory_items: Mapped[list[DurableMemoryItem]] = relationship(
        "DurableMemoryItem", back_populates="transcript"
    )


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

    session: Mapped[MemorySession] = relationship("MemorySession", back_populates="observations")
    transcript: Mapped[Transcript | None] = relationship("Transcript", back_populates="observations")


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

    transcript: Mapped[Transcript] = relationship("Transcript", back_populates="entries")
