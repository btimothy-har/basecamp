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
    text,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from pi_memory.constants import (
    DURABLE_MEMORY_SOURCE_KIND_CLAIM,
    DURABLE_MEMORY_STATUS_CANDIDATE,
    SOURCE_ORIGIN_UNKNOWN,
)
from pi_memory.db.base import Base

if TYPE_CHECKING:
    from pi_memory.db.models.analysis import ActivityUnit
    from pi_memory.db.models.ingestion import (
        MemorySession,
        Transcript,
    )
    from pi_memory.db.models.interpretation import (
        SessionInterpretationQualityReport,
        SessionInterpretationSnapshot,
    )
    from pi_memory.db.models.jobs import Job
    from pi_memory.db.models.projection import MemoryProjectionRecord


class DurableMemoryItem(Base):
    """Canonical durable memory item promoted from session interpretation claims."""

    __tablename__ = "durable_memory_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'promoted', 'quarantined', 'rejected', 'archived')",
            name="ck_durable_memory_items_status_valid",
        ),
        CheckConstraint(
            "status_reason IS NULL OR length(status_reason) > 0",
            name="ck_durable_memory_items_status_reason_non_empty",
        ),
        CheckConstraint(
            "archived_reason IS NULL OR archived_reason IN "
            "('superseded', 'stale', 'manually_retired', 'source_invalidated')",
            name="ck_durable_memory_items_archived_reason_valid",
        ),
        CheckConstraint(
            "(status = 'archived' AND archived_reason IS NOT NULL) OR "
            "(status != 'archived' AND archived_reason IS NULL)",
            name="ck_durable_memory_items_archived_reason_matches_status",
        ),
        CheckConstraint(
            "CASE WHEN archived_reason = 'superseded' THEN superseded_by_id IS NOT NULL "
            "ELSE superseded_by_id IS NULL END",
            name="ck_durable_memory_items_superseded_by_matches_reason",
        ),
        CheckConstraint(
            "superseded_by_id IS NULL OR superseded_by_id != id",
            name="ck_durable_memory_items_not_self_superseded",
        ),
        CheckConstraint("claim_index >= 0", name="ck_durable_memory_items_claim_index_non_negative"),
        CheckConstraint("length(claim_kind) > 0", name="ck_durable_memory_items_claim_kind_non_empty"),
        CheckConstraint("length(statement) > 0", name="ck_durable_memory_items_statement_non_empty"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_durable_memory_items_confidence_range",
        ),
        CheckConstraint("length(content_hash) > 0", name="ck_durable_memory_items_content_hash_non_empty"),
        CheckConstraint("schema_version > 0", name="ck_durable_memory_items_schema_version_positive"),
        Index("ix_durable_memory_items_session_status", "session_id", "status"),
        Index("ix_durable_memory_items_snapshot_id", "snapshot_id"),
        Index("ix_durable_memory_items_quality_report_id", "quality_report_id"),
        Index("ix_durable_memory_items_content_hash", "content_hash"),
        Index("ix_durable_memory_items_superseded_by_id", "superseded_by_id"),
        Index("ix_durable_memory_items_job_id", "job_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    transcript_id: Mapped[int | None] = mapped_column(ForeignKey("transcripts.id", ondelete="SET NULL"), index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("session_interpretation_snapshots.id", ondelete="CASCADE"))
    quality_report_id: Mapped[int] = mapped_column(
        ForeignKey("session_interpretation_quality_reports.id", ondelete="CASCADE"),
    )
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("durable_memory_items.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(
        default=DURABLE_MEMORY_STATUS_CANDIDATE,
        server_default=DURABLE_MEMORY_STATUS_CANDIDATE,
    )
    status_reason: Mapped[str | None]
    archived_reason: Mapped[str | None]
    claim_index: Mapped[int]
    claim_kind: Mapped[str]
    statement: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None]
    content_hash: Mapped[str]
    evaluation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    relation_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    schema_version: Mapped[int] = mapped_column(default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    session: Mapped[MemorySession] = relationship("MemorySession", back_populates="durable_memory_items")
    transcript: Mapped[Transcript | None] = relationship("Transcript", back_populates="durable_memory_items")
    snapshot: Mapped[SessionInterpretationSnapshot] = relationship(
        "SessionInterpretationSnapshot", back_populates="durable_memory_items"
    )
    quality_report: Mapped[SessionInterpretationQualityReport] = relationship(
        "SessionInterpretationQualityReport", back_populates="durable_memory_items"
    )
    job: Mapped[Job | None] = relationship("Job", back_populates="durable_memory_items")
    superseded_by: Mapped[DurableMemoryItem | None] = relationship(
        "DurableMemoryItem",
        back_populates="superseded_items",
        remote_side=[id],
    )
    superseded_items: Mapped[list[DurableMemoryItem]] = relationship(
        "DurableMemoryItem", back_populates="superseded_by"
    )
    sources: Mapped[list[DurableMemorySource]] = relationship(
        "DurableMemorySource",
        back_populates="memory",
        cascade="all, delete-orphan",
    )
    relations: Mapped[list[DurableMemoryRelation]] = relationship(
        "DurableMemoryRelation",
        back_populates="memory",
        cascade="all, delete-orphan",
        foreign_keys="DurableMemoryRelation.memory_id",
    )
    related_by_relations: Mapped[list[DurableMemoryRelation]] = relationship(
        "DurableMemoryRelation",
        back_populates="related_memory",
        foreign_keys="DurableMemoryRelation.related_memory_id",
    )
    projection_records: Mapped[list[MemoryProjectionRecord]] = relationship(
        "MemoryProjectionRecord", back_populates="durable_memory"
    )
    audit_events: Mapped[list[DurableMemoryAuditEvent]] = relationship(
        "DurableMemoryAuditEvent",
        back_populates="memory",
        cascade="all, delete-orphan",
    )


class DurableMemorySource(Base):
    """Source link from a durable memory item back to interpretation evidence."""

    __tablename__ = "durable_memory_sources"
    __table_args__ = (
        UniqueConstraint("memory_id", "source_ref", "source_kind", name="uq_durable_memory_sources_memory_ref_kind"),
        CheckConstraint("claim_index >= 0", name="ck_durable_memory_sources_claim_index_non_negative"),
        CheckConstraint("length(source_ref) > 0", name="ck_durable_memory_sources_source_ref_non_empty"),
        CheckConstraint(
            "source_origin IN ('local', 'inherited', 'mixed', 'unknown')",
            name="ck_durable_memory_sources_source_origin_valid",
        ),
        CheckConstraint(
            "source_kind IN ('claim', 'supporting_context')",
            name="ck_durable_memory_sources_source_kind_valid",
        ),
        Index("ix_durable_memory_sources_memory_id", "memory_id"),
        Index("ix_durable_memory_sources_snapshot_id", "snapshot_id"),
        Index("ix_durable_memory_sources_source_ref", "source_ref"),
        Index("ix_durable_memory_sources_activity_unit_id", "activity_unit_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    memory_id: Mapped[int] = mapped_column(ForeignKey("durable_memory_items.id", ondelete="CASCADE"))
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("session_interpretation_snapshots.id", ondelete="CASCADE"))
    quality_report_id: Mapped[int] = mapped_column(
        ForeignKey("session_interpretation_quality_reports.id", ondelete="CASCADE"),
    )
    activity_unit_id: Mapped[int | None] = mapped_column(ForeignKey("activity_units.id", ondelete="SET NULL"))
    claim_index: Mapped[int]
    source_ref: Mapped[str]
    source_origin: Mapped[str] = mapped_column(default=SOURCE_ORIGIN_UNKNOWN, server_default=SOURCE_ORIGIN_UNKNOWN)
    source_kind: Mapped[str] = mapped_column(
        default=DURABLE_MEMORY_SOURCE_KIND_CLAIM,
        server_default=DURABLE_MEMORY_SOURCE_KIND_CLAIM,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    memory: Mapped[DurableMemoryItem] = relationship("DurableMemoryItem", back_populates="sources")
    snapshot: Mapped[SessionInterpretationSnapshot] = relationship(
        "SessionInterpretationSnapshot", back_populates="durable_memory_sources"
    )
    quality_report: Mapped[SessionInterpretationQualityReport] = relationship(
        "SessionInterpretationQualityReport", back_populates="durable_memory_sources"
    )
    activity_unit: Mapped[ActivityUnit | None] = relationship("ActivityUnit", back_populates="durable_memory_sources")


class DurableMemoryRelation(Base):
    """Typed relation between durable memory items."""

    __tablename__ = "durable_memory_relations"
    __table_args__ = (
        UniqueConstraint(
            "memory_id",
            "related_memory_id",
            "relation_type",
            name="uq_durable_memory_relations_memory_related_type",
        ),
        CheckConstraint(
            "relation_type IN "
            "('novel', 'duplicate', 'reinforces', 'refines', 'conflicts', 'supersedes', 'stale_signal')",
            name="ck_durable_memory_relations_relation_type_valid",
        ),
        CheckConstraint("memory_id != related_memory_id", name="ck_durable_memory_relations_not_self"),
        CheckConstraint(
            "similarity_score IS NULL OR (similarity_score >= 0 AND similarity_score <= 1)",
            name="ck_durable_memory_relations_similarity_score_range",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_durable_memory_relations_confidence_range",
        ),
        Index("ix_durable_memory_relations_memory_id", "memory_id"),
        Index("ix_durable_memory_relations_related_memory_id", "related_memory_id"),
        Index("ix_durable_memory_relations_relation_type", "relation_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    memory_id: Mapped[int] = mapped_column(ForeignKey("durable_memory_items.id", ondelete="CASCADE"))
    related_memory_id: Mapped[int] = mapped_column(ForeignKey("durable_memory_items.id", ondelete="CASCADE"))
    relation_type: Mapped[str]
    similarity_score: Mapped[float | None]
    confidence: Mapped[float | None]
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    memory: Mapped[DurableMemoryItem] = relationship(
        "DurableMemoryItem",
        back_populates="relations",
        foreign_keys=[memory_id],
    )
    related_memory: Mapped[DurableMemoryItem] = relationship(
        "DurableMemoryItem",
        back_populates="related_by_relations",
        foreign_keys=[related_memory_id],
    )


class DurableMemoryAuditEvent(Base):
    """Audit event for durable memory status and metadata changes."""

    __tablename__ = "durable_memory_audit_events"
    __table_args__ = (
        CheckConstraint("length(event_type) > 0", name="ck_durable_memory_audit_events_event_type_non_empty"),
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('candidate', 'promoted', 'quarantined', 'rejected', 'archived')",
            name="ck_durable_memory_audit_events_from_status_valid",
        ),
        CheckConstraint(
            "to_status IS NULL OR to_status IN ('candidate', 'promoted', 'quarantined', 'rejected', 'archived')",
            name="ck_durable_memory_audit_events_to_status_valid",
        ),
        CheckConstraint(
            "reason_code IS NULL OR length(reason_code) > 0",
            name="ck_durable_memory_audit_events_reason_code_non_empty",
        ),
        Index("ix_durable_memory_audit_events_memory_created", "memory_id", "created_at"),
        Index("ix_durable_memory_audit_events_job_id", "job_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    memory_id: Mapped[int] = mapped_column(ForeignKey("durable_memory_items.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    event_type: Mapped[str]
    from_status: Mapped[str | None]
    to_status: Mapped[str | None]
    reason_code: Mapped[str | None]
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    memory: Mapped[DurableMemoryItem] = relationship("DurableMemoryItem", back_populates="audit_events")
    job: Mapped[Job | None] = relationship("Job", back_populates="durable_memory_audit_events")
