from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Index,
    Text,
    func,
    text,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from pi_memory.constants import JOB_STATUS_QUEUED
from pi_memory.db.base import Base

if TYPE_CHECKING:
    from pi_memory.db.models.analysis import AnalysisRun
    from pi_memory.db.models.durable import (
        DurableMemoryAuditEvent,
        DurableMemoryItem,
    )
    from pi_memory.db.models.interpretation import (
        EpisodeInterpretationSnapshot,
        SessionInterpretationQualityReport,
        SessionInterpretationSnapshot,
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
        Index("uq_jobs_idempotency_key", "idempotency_key", unique=True),
        Index("ix_jobs_status_updated", "status", "updated_at"),
        Index("ix_jobs_kind_status", "kind", "status"),
        Index("ix_jobs_run_id", "run_id"),
        Index("ix_jobs_status_lease_expires", "status", "lease_expires_at"),
        Index("ix_jobs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]
    idempotency_key: Mapped[str | None]
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

    analysis_runs: Mapped[list[AnalysisRun]] = relationship("AnalysisRun", back_populates="job")
    episode_interpretation_snapshots: Mapped[list[EpisodeInterpretationSnapshot]] = relationship(
        "EpisodeInterpretationSnapshot", back_populates="job"
    )
    session_interpretation_snapshots: Mapped[list[SessionInterpretationSnapshot]] = relationship(
        "SessionInterpretationSnapshot", back_populates="job"
    )
    session_interpretation_quality_reports: Mapped[list[SessionInterpretationQualityReport]] = relationship(
        "SessionInterpretationQualityReport",
        back_populates="job",
    )
    durable_memory_items: Mapped[list[DurableMemoryItem]] = relationship("DurableMemoryItem", back_populates="job")
    durable_memory_audit_events: Mapped[list[DurableMemoryAuditEvent]] = relationship(
        "DurableMemoryAuditEvent", back_populates="job"
    )
