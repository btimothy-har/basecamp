"""Projection metadata helpers for SQLite-backed memory records."""

from __future__ import annotations

from pi_memory.db.models import MemoryProjectionRecord
from pi_memory.projection.contracts import ProjectionMetadataValue


def projection_metadata_from_record(record: MemoryProjectionRecord) -> dict[str, ProjectionMetadataValue]:
    """Build scalar Chroma-safe metadata from a canonical projection record.

    Nullable pointer/model fields are omitted when absent. The helper only reads ORM
    fields and does not mutate SQLite state.
    """
    metadata: dict[str, ProjectionMetadataValue] = {
        "collection_name": record.collection_name,
        "record_type": record.record_type,
        "memory_layer": record.memory_layer,
        "source_table": record.source_table,
        "source_id": record.source_id,
        "content_hash": record.content_hash,
        "projection_status": record.status,
        "recall_visible": record.recall_visible,
        "relation_visible": record.relation_visible,
    }
    nullable_fields = {
        "snapshot_id": record.snapshot_id,
        "quality_report_id": record.quality_report_id,
        "durable_memory_id": record.durable_memory_id,
        "claim_index": record.claim_index,
        "embedding_model": record.embedding_model,
        "embedding_dimension": record.embedding_dimension,
    }
    metadata.update({key: value for key, value in nullable_fields.items() if value is not None})
    return metadata
