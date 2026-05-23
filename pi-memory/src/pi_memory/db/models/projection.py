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

from pi_memory.constants import (
    MEMORY_PROJECTION_COLLECTION_NAME,
    MEMORY_PROJECTION_STATUS_PENDING,
)
from pi_memory.db.base import Base

if TYPE_CHECKING:
    from pi_memory.db.models.durable import DurableMemoryItem
    from pi_memory.db.models.interpretation import (
        SessionInterpretationQualityReport,
        SessionInterpretationSnapshot,
    )


class MemoryProjectionRecord(Base):
    """Rebuildable Chroma projection metadata with SQLite record pointers."""

    __tablename__ = "memory_projection_records"
    __table_args__ = (
        UniqueConstraint("collection_name", "chroma_id", name="uq_memory_projection_records_collection_chroma_id"),
        UniqueConstraint("collection_name", "record_key", name="uq_memory_projection_records_collection_record_key"),
        CheckConstraint("length(collection_name) > 0", name="ck_memory_projection_records_collection_name_non_empty"),
        CheckConstraint("length(chroma_id) > 0", name="ck_memory_projection_records_chroma_id_non_empty"),
        CheckConstraint("length(record_key) > 0", name="ck_memory_projection_records_record_key_non_empty"),
        CheckConstraint(
            "record_type IN ('session_claim', 'durable_memory')",
            name="ck_memory_projection_records_record_type_valid",
        ),
        CheckConstraint(
            "memory_layer IN ('short_term', 'long_term')",
            name="ck_memory_projection_records_memory_layer_valid",
        ),
        CheckConstraint("length(source_table) > 0", name="ck_memory_projection_records_source_table_non_empty"),
        CheckConstraint("source_id > 0", name="ck_memory_projection_records_source_id_positive"),
        CheckConstraint(
            "claim_index IS NULL OR claim_index >= 0",
            name="ck_memory_projection_records_claim_index_non_negative",
        ),
        CheckConstraint("length(content_hash) > 0", name="ck_memory_projection_records_content_hash_non_empty"),
        CheckConstraint(
            "embedding_model IS NULL OR length(embedding_model) > 0",
            name="ck_memory_projection_records_embedding_model_non_empty",
        ),
        CheckConstraint(
            "embedding_dimension IS NULL OR embedding_dimension > 0",
            name="ck_memory_projection_records_embedding_dimension_positive",
        ),
        CheckConstraint(
            "status IN ('pending', 'indexed', 'stale', 'failed', 'deleted')",
            name="ck_memory_projection_records_status_valid",
        ),
        CheckConstraint(
            "(record_type = 'session_claim' AND snapshot_id IS NOT NULL "
            "AND claim_index IS NOT NULL AND claim_index >= 0 "
            "AND durable_memory_id IS NULL AND memory_layer = 'short_term') OR "
            "(record_type = 'durable_memory' AND snapshot_id IS NULL "
            "AND durable_memory_id IS NOT NULL AND claim_index IS NULL "
            "AND memory_layer = 'long_term')",
            name="ck_memory_projection_records_record_type_invariants",
        ),
        Index("ix_memory_projection_records_collection_status", "collection_name", "status"),
        Index("ix_memory_projection_records_source", "source_table", "source_id"),
        Index("ix_memory_projection_records_snapshot_id", "snapshot_id"),
        Index("ix_memory_projection_records_quality_report_id", "quality_report_id"),
        Index("ix_memory_projection_records_durable_memory_id", "durable_memory_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_name: Mapped[str] = mapped_column(
        default=MEMORY_PROJECTION_COLLECTION_NAME,
        server_default=MEMORY_PROJECTION_COLLECTION_NAME,
    )
    chroma_id: Mapped[str]
    record_key: Mapped[str]
    record_type: Mapped[str]
    memory_layer: Mapped[str]
    source_table: Mapped[str]
    source_id: Mapped[int]
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("session_interpretation_snapshots.id", ondelete="CASCADE"),
    )
    quality_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("session_interpretation_quality_reports.id", ondelete="CASCADE"),
    )
    durable_memory_id: Mapped[int | None] = mapped_column(ForeignKey("durable_memory_items.id", ondelete="CASCADE"))
    claim_index: Mapped[int | None]
    content_hash: Mapped[str]
    embedding_model: Mapped[str | None]
    embedding_dimension: Mapped[int | None]
    status: Mapped[str] = mapped_column(
        default=MEMORY_PROJECTION_STATUS_PENDING,
        server_default=MEMORY_PROJECTION_STATUS_PENDING,
    )
    recall_visible: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    relation_visible: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    last_error: Mapped[str | None] = mapped_column(Text)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    snapshot: Mapped[SessionInterpretationSnapshot | None] = relationship(
        "SessionInterpretationSnapshot", back_populates="projection_records"
    )
    quality_report: Mapped[SessionInterpretationQualityReport | None] = relationship(
        "SessionInterpretationQualityReport",
        back_populates="projection_records",
    )
    durable_memory: Mapped[DurableMemoryItem | None] = relationship(
        "DurableMemoryItem", back_populates="projection_records"
    )
