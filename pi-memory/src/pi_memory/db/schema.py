"""SQLAlchemy schema for pi-memory."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for pi-memory ORM models."""


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
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

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
