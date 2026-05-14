"""SQLAlchemy schema for pi-memory."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint, func, text
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
