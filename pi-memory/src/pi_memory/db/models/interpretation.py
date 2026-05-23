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
    SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED,
)

if TYPE_CHECKING:
    from pi_memory.db.models.analysis import (
        AnalysisRun,
        Episode,
    )
    from pi_memory.db.models.durable import (
        DurableMemoryItem,
        DurableMemorySource,
    )
    from pi_memory.db.models.ingestion import (
        MemorySession,
        Transcript,
    )
    from pi_memory.db.models.jobs import Job
    from pi_memory.db.models.projection import MemoryProjectionRecord


class EpisodeInterpretationSnapshot(Base):
    """Persisted interpretation result for one deterministic episode."""

    __tablename__ = "episode_interpretation_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id",
            "episode_id",
            name="uq_episode_interpretation_snapshots_analysis_episode",
        ),
        CheckConstraint(
            "status IN ('completed', 'skipped_no_claim_sources', 'failed')",
            name="ck_episode_interpretation_snapshots_status_valid",
        ),
        CheckConstraint("episode_ordinal >= 0", name="ck_episode_interpretation_snapshots_ordinal_non_negative"),
        CheckConstraint("activity_count >= 0", name="ck_episode_interpretation_snapshots_activity_count_non_negative"),
        CheckConstraint(
            "claim_source_activity_count >= 0",
            name="ck_episode_interpretation_snapshots_claim_source_activity_count_non_negative",
        ),
        CheckConstraint(
            "analyzed_through_byte_offset >= 0",
            name="ck_episode_interpretation_snapshots_byte_offset_non_negative",
        ),
        CheckConstraint("schema_version > 0", name="ck_episode_interpretation_snapshots_schema_version_positive"),
        Index(
            "ix_episode_interpretation_snapshots_analysis_ordinal",
            "analysis_run_id",
            "episode_ordinal",
        ),
        Index("ix_episode_interpretation_snapshots_status_updated_at", "status", "updated_at"),
        Index("ix_episode_interpretation_snapshots_job_id", "job_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"), index=True)
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    status: Mapped[str]
    episode_ordinal: Mapped[int] = mapped_column(default=0, server_default="0")
    activity_count: Mapped[int] = mapped_column(default=0, server_default="0")
    claim_source_activity_count: Mapped[int] = mapped_column(default=0, server_default="0")
    analyzed_through_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("transcript_entries.id", ondelete="SET NULL"),
        index=True,
    )
    analyzed_through_byte_offset: Mapped[int] = mapped_column(default=0, server_default="0")
    interpretation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    model_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    failure_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    prompt_version: Mapped[str | None]
    schema_version: Mapped[int] = mapped_column(default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    session: Mapped[MemorySession] = relationship("MemorySession", back_populates="episode_interpretation_snapshots")
    transcript: Mapped[Transcript] = relationship("Transcript", back_populates="episode_interpretation_snapshots")
    analysis_run: Mapped[AnalysisRun] = relationship("AnalysisRun", back_populates="episode_interpretation_snapshots")
    episode: Mapped[Episode] = relationship("Episode", back_populates="interpretation_snapshot")
    job: Mapped[Job | None] = relationship("Job", back_populates="episode_interpretation_snapshots")


class SessionInterpretationSnapshot(Base):
    """Replaceable current interpretation snapshot for a session."""

    __tablename__ = "session_interpretation_snapshots"
    __table_args__ = (
        CheckConstraint(
            "status IN ('completed', 'blocked', 'skipped_no_claim_sources')",
            name="ck_session_interpretation_snapshots_status_valid",
        ),
        CheckConstraint(
            "blocked_reason IS NULL OR blocked_reason IN ("
            "'phase_5a_not_ready', 'parent_transcript_not_ingested', 'source_origin_incomplete')",
            name="ck_session_interpretation_snapshots_blocked_reason_valid",
        ),
        CheckConstraint(
            "(status = 'blocked' AND blocked_reason IS NOT NULL) OR (status != 'blocked' AND blocked_reason IS NULL)",
            name="ck_session_interpretation_snapshots_blocked_reason_matches_status",
        ),
        CheckConstraint(
            "analyzed_through_byte_offset >= 0",
            name="ck_session_interpretation_snapshots_byte_offset_non_negative",
        ),
        CheckConstraint(
            "claim_source_activity_count >= 0",
            name="ck_session_interpretation_snapshots_claim_source_activity_count_non_negative",
        ),
        CheckConstraint("schema_version > 0", name="ck_session_interpretation_snapshots_schema_version_positive"),
        Index("ix_session_interpretation_snapshots_status_updated_at", "status", "updated_at"),
        Index("ix_session_interpretation_snapshots_analysis_run_id", "analysis_run_id"),
        Index("ix_session_interpretation_snapshots_job_id", "job_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), unique=True, index=True)
    transcript_id: Mapped[int | None] = mapped_column(ForeignKey("transcripts.id", ondelete="SET NULL"), index=True)
    analysis_run_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_runs.id", ondelete="SET NULL"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    status: Mapped[str]
    blocked_reason: Mapped[str | None]
    analyzed_through_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("transcript_entries.id", ondelete="SET NULL"),
        index=True,
    )
    analyzed_through_byte_offset: Mapped[int] = mapped_column(default=0, server_default="0")
    origin_counts_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    claim_source_activity_count: Mapped[int] = mapped_column(default=0, server_default="0")
    interpretation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    model_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    prompt_version: Mapped[str | None]
    schema_version: Mapped[int] = mapped_column(default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    session: Mapped[MemorySession] = relationship("MemorySession", back_populates="session_interpretation_snapshot")
    transcript: Mapped[Transcript | None] = relationship(
        "Transcript", back_populates="session_interpretation_snapshots"
    )
    analysis_run: Mapped[AnalysisRun | None] = relationship(
        "AnalysisRun", back_populates="session_interpretation_snapshots"
    )
    job: Mapped[Job | None] = relationship("Job", back_populates="session_interpretation_snapshots")
    quality_report: Mapped[SessionInterpretationQualityReport | None] = relationship(
        "SessionInterpretationQualityReport",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )
    durable_memory_items: Mapped[list[DurableMemoryItem]] = relationship(
        "DurableMemoryItem",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )
    durable_memory_sources: Mapped[list[DurableMemorySource]] = relationship(
        "DurableMemorySource",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )
    projection_records: Mapped[list[MemoryProjectionRecord]] = relationship(
        "MemoryProjectionRecord", back_populates="snapshot"
    )


class SessionInterpretationQualityReport(Base):
    """Persisted quality assessment report for an interpretation snapshot."""

    __tablename__ = "session_interpretation_quality_reports"
    __table_args__ = (
        CheckConstraint(
            "quality_status IN ('healthy', 'degraded', 'failed', 'not_assessed', 'assessment_failed')",
            name="ck_session_interpretation_quality_reports_quality_status_valid",
        ),
        CheckConstraint(
            "quality_reason IS NULL OR quality_reason IN ("
            "'blocked_interpretation', 'skipped_no_claim_sources', 'outdated_derivation', "
            "'superseded_snapshot', 'deterministic_integrity_failed', 'semantic_degraded', "
            "'semantic_failed', 'semantic_assessment_pending', 'semantic_assessment_failed')",
            name="ck_session_interpretation_quality_reports_quality_reason_valid",
        ),
        CheckConstraint(
            "(quality_status = 'healthy' AND quality_reason IS NULL) OR "
            "(quality_status != 'healthy' AND quality_reason IS NOT NULL)",
            name="ck_session_interpretation_quality_reports_quality_reason_matches_status",
        ),
        CheckConstraint(
            "derivation_status IN ('current', 'outdated', 'superseded')",
            name="ck_session_interpretation_quality_reports_derivation_status_valid",
        ),
        CheckConstraint(
            "deterministic_status IN ('passed', 'failed', 'not_applicable')",
            name="ck_session_interpretation_quality_reports_deterministic_status_valid",
        ),
        CheckConstraint(
            "semantic_status IN ('passed', 'degraded', 'failed', 'not_assessed', 'assessment_failed')",
            name="ck_session_interpretation_quality_reports_semantic_status_valid",
        ),
        CheckConstraint("schema_version > 0", name="ck_session_interpretation_quality_reports_schema_version_positive"),
        Index("ix_session_interpretation_quality_reports_quality_status_updated_at", "quality_status", "updated_at"),
        Index(
            "ix_session_interpretation_quality_reports_derivation_status_quality_status",
            "derivation_status",
            "quality_status",
        ),
        Index("ix_session_interpretation_quality_reports_promotable_updated_at", "promotable", "updated_at"),
        Index("ix_session_interpretation_quality_reports_job_id", "job_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("session_interpretation_snapshots.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    quality_status: Mapped[str]
    quality_reason: Mapped[str | None]
    derivation_status: Mapped[str] = mapped_column(
        default=SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
        server_default=SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
    )
    deterministic_status: Mapped[str] = mapped_column(
        default=SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
        server_default=SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
    )
    semantic_status: Mapped[str] = mapped_column(
        default=SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED,
        server_default=SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED,
    )
    promotable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    deterministic_findings_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        server_default=text("'[]'"),
    )
    semantic_findings_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        server_default=text("'[]'"),
    )
    claim_assessments_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        server_default=text("'[]'"),
    )
    missing_high_signal_items_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        server_default=text("'[]'"),
    )
    model_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    assessment_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    prompt_version: Mapped[str | None]
    schema_version: Mapped[int] = mapped_column(default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    snapshot: Mapped[SessionInterpretationSnapshot] = relationship(
        "SessionInterpretationSnapshot", back_populates="quality_report"
    )
    job: Mapped[Job | None] = relationship("Job", back_populates="session_interpretation_quality_reports")
    durable_memory_items: Mapped[list[DurableMemoryItem]] = relationship(
        "DurableMemoryItem",
        back_populates="quality_report",
        cascade="all, delete-orphan",
    )
    durable_memory_sources: Mapped[list[DurableMemorySource]] = relationship(
        "DurableMemorySource",
        back_populates="quality_report",
        cascade="all, delete-orphan",
    )
    projection_records: Mapped[list[MemoryProjectionRecord]] = relationship(
        "MemoryProjectionRecord", back_populates="quality_report"
    )
