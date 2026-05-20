"""Read-only durable memory inspection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from pi_memory.db import (
    DURABLE_MEMORY_STATUSES,
    MEMORY_LAYERS,
    MEMORY_PROJECTION_RECORD_TYPES,
    MEMORY_PROJECTION_STATUSES,
    Database,
    DurableMemoryAuditEvent,
    DurableMemoryItem,
    DurableMemoryRelation,
    DurableMemorySource,
    MemoryProjectionRecord,
    MemorySession,
    database,
)


@dataclass(frozen=True)
class DurableMemoryListResult:
    """Paginated durable memory inspection result."""

    results: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
    query: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return _list_payload(
            results=self.results,
            total=self.total,
            limit=self.limit,
            offset=self.offset,
            query=self.query,
        )


@dataclass(frozen=True)
class DurableMemoryAuditListResult:
    """Paginated durable memory audit inspection result."""

    results: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
    query: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return _list_payload(
            results=self.results,
            total=self.total,
            limit=self.limit,
            offset=self.offset,
            query=self.query,
        )


@dataclass(frozen=True)
class MemoryProjectionListResult:
    """Paginated memory projection record inspection result."""

    results: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
    query: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return _list_payload(
            results=self.results,
            total=self.total,
            limit=self.limit,
            offset=self.offset,
            query=self.query,
        )


class DurableMemoryFilterError(ValueError):
    """Raised when durable memory inspection filters are invalid."""

    @classmethod
    def invalid_status(cls, value: str) -> DurableMemoryFilterError:
        return cls(f"Invalid status: {value}")

    @classmethod
    def invalid_record_type(cls, value: str) -> DurableMemoryFilterError:
        return cls(f"Invalid record_type: {value}")

    @classmethod
    def invalid_memory_layer(cls, value: str) -> DurableMemoryFilterError:
        return cls(f"Invalid memory_layer: {value}")

    @classmethod
    def invalid_projection_status(cls, value: str) -> DurableMemoryFilterError:
        return cls(f"Invalid projection_status: {value}")

    @classmethod
    def invalid_limit(cls) -> DurableMemoryFilterError:
        return cls("limit must be between 1 and 100")

    @classmethod
    def invalid_offset(cls) -> DurableMemoryFilterError:
        return cls("offset must be non-negative")


class DurableMemoryInspectionService:
    """Inspect persisted durable memory state using read-only queries."""

    def __init__(self, database: Database = database) -> None:
        self._database = database

    def get_memory(self, memory_id: int, *, include_audit: bool = False) -> dict[str, Any] | None:
        """Return a safe durable memory payload by row id."""
        self._database.initialize()
        with self._database.session() as db_session:
            memory = db_session.scalar(
                select(DurableMemoryItem)
                .where(DurableMemoryItem.id == memory_id)
                .options(
                    selectinload(DurableMemoryItem.session),
                    selectinload(DurableMemoryItem.sources),
                    selectinload(DurableMemoryItem.relations),
                    selectinload(DurableMemoryItem.related_by_relations),
                    selectinload(DurableMemoryItem.projection_records),
                    selectinload(DurableMemoryItem.audit_events),
                ),
            )
            if memory is None:
                return None
            return serialize_durable_memory(memory, include_audit=include_audit)

    def list_memories(
        self,
        *,
        status: str | None = None,
        cwd: str | None = None,
        worktree_label: str | None = None,
        session_id: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> DurableMemoryListResult:
        """Return durable memories with optional filters and pagination."""
        _validate_memory_filters(status=status, limit=limit, offset=offset)
        self._database.initialize()
        query_values = _query_payload(
            status=status,
            cwd=cwd,
            worktree_label=worktree_label,
            session_id=session_id,
            limit=limit,
            offset=offset,
        )
        with self._database.session() as db_session:
            filtered = _apply_memory_filters(
                _memory_rows(),
                status=status,
                cwd=cwd,
                worktree_label=worktree_label,
                session_id=session_id,
            )
            total = int(
                db_session.scalar(
                    _apply_memory_filters(
                        select(func.count()).select_from(DurableMemoryItem).join(MemorySession),
                        status=status,
                        cwd=cwd,
                        worktree_label=worktree_label,
                        session_id=session_id,
                    ),
                )
                or 0,
            )
            rows = db_session.execute(
                filtered.order_by(DurableMemoryItem.updated_at.desc(), DurableMemoryItem.id.desc())
                .offset(offset)
                .limit(limit),
            ).all()
        return DurableMemoryListResult(
            results=[serialize_durable_memory(memory, memory_session=session) for memory, session in rows],
            total=total,
            limit=limit,
            offset=offset,
            query=query_values,
        )

    def list_audit_events(
        self,
        memory_id: int,
        *,
        limit: int = 10,
        offset: int = 0,
    ) -> DurableMemoryAuditListResult | None:
        """Return audit events for one durable memory with pagination."""
        _validate_pagination(limit=limit, offset=offset)
        self._database.initialize()
        query_values = _query_payload(memory_id=memory_id, limit=limit, offset=offset)
        with self._database.session() as db_session:
            exists = db_session.scalar(select(DurableMemoryItem.id).where(DurableMemoryItem.id == memory_id))
            if exists is None:
                return None
            base = select(DurableMemoryAuditEvent).where(DurableMemoryAuditEvent.memory_id == memory_id)
            total = int(
                db_session.scalar(
                    select(func.count())
                    .select_from(DurableMemoryAuditEvent)
                    .where(DurableMemoryAuditEvent.memory_id == memory_id),
                )
                or 0,
            )
            events = db_session.scalars(
                base.order_by(DurableMemoryAuditEvent.created_at.asc(), DurableMemoryAuditEvent.id.asc())
                .offset(offset)
                .limit(limit),
            ).all()
        return DurableMemoryAuditListResult(
            results=[serialize_durable_memory_audit_event(event) for event in events],
            total=total,
            limit=limit,
            offset=offset,
            query=query_values,
        )

    def list_projection_records(
        self,
        *,
        record_type: str | None = None,
        memory_layer: str | None = None,
        projection_status: str | None = None,
        recall_visible: bool | None = None,
        relation_visible: bool | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> MemoryProjectionListResult:
        """Return memory projection records with optional filters and pagination."""
        _validate_projection_filters(
            record_type=record_type,
            memory_layer=memory_layer,
            projection_status=projection_status,
            limit=limit,
            offset=offset,
        )
        self._database.initialize()
        query_values = _query_payload(
            record_type=record_type,
            memory_layer=memory_layer,
            projection_status=projection_status,
            recall_visible=recall_visible,
            relation_visible=relation_visible,
            limit=limit,
            offset=offset,
        )
        with self._database.session() as db_session:
            filtered = _apply_projection_filters(
                select(MemoryProjectionRecord),
                record_type=record_type,
                memory_layer=memory_layer,
                projection_status=projection_status,
                recall_visible=recall_visible,
                relation_visible=relation_visible,
            )
            total = int(
                db_session.scalar(
                    _apply_projection_filters(
                        select(func.count()).select_from(MemoryProjectionRecord),
                        record_type=record_type,
                        memory_layer=memory_layer,
                        projection_status=projection_status,
                        recall_visible=recall_visible,
                        relation_visible=relation_visible,
                    ),
                )
                or 0,
            )
            records = db_session.scalars(
                filtered.order_by(MemoryProjectionRecord.updated_at.desc(), MemoryProjectionRecord.id.desc())
                .offset(offset)
                .limit(limit),
            ).all()
        return MemoryProjectionListResult(
            results=[serialize_memory_projection_record(record) for record in records],
            total=total,
            limit=limit,
            offset=offset,
            query=query_values,
        )


def serialize_durable_memory(
    memory: DurableMemoryItem,
    *,
    memory_session: MemorySession | None = None,
    include_audit: bool = False,
) -> dict[str, Any]:
    """Return a JSON-safe durable memory payload without raw transcript rows."""
    session = memory_session or memory.session
    payload: dict[str, Any] = {
        "memory_id": memory.id,
        "session_id": session.session_id,
        "session_row_id": session.id,
        "session_metadata": _session_metadata(session),
        "transcript_id": memory.transcript_id,
        "snapshot_id": memory.snapshot_id,
        "quality_report_id": memory.quality_report_id,
        "job_id": memory.job_id,
        "superseded_by_id": memory.superseded_by_id,
        "status": memory.status,
        "status_reason": memory.status_reason,
        "archived_reason": memory.archived_reason,
        "claim_index": memory.claim_index,
        "claim_kind": memory.claim_kind,
        "statement": memory.statement,
        "confidence": memory.confidence,
        "content_hash": memory.content_hash,
        "evaluation_json": dict(memory.evaluation_json),
        "relation_summary_json": dict(memory.relation_summary_json),
        "metadata_json": dict(memory.metadata_json),
        "schema_version": memory.schema_version,
        "created_at": _serialize_datetime(memory.created_at),
        "updated_at": _serialize_datetime(memory.updated_at),
        "sources": [serialize_durable_memory_source(source) for source in memory.sources],
        "relations_from": [serialize_durable_memory_relation(relation) for relation in memory.relations],
        "relations_to": [serialize_durable_memory_relation(relation) for relation in memory.related_by_relations],
        "projection_records": [serialize_memory_projection_record(record) for record in memory.projection_records],
    }
    if include_audit:
        payload["audit_events"] = [
            serialize_durable_memory_audit_event(event)
            for event in sorted(memory.audit_events, key=lambda event: (event.created_at, event.id))
        ]
    return payload


def serialize_durable_memory_source(source: DurableMemorySource) -> dict[str, Any]:
    """Return a JSON-safe durable memory source payload."""
    return {
        "source_id": source.id,
        "memory_id": source.memory_id,
        "snapshot_id": source.snapshot_id,
        "quality_report_id": source.quality_report_id,
        "activity_unit_id": source.activity_unit_id,
        "claim_index": source.claim_index,
        "source_ref": source.source_ref,
        "source_origin": source.source_origin,
        "source_kind": source.source_kind,
        "metadata_json": dict(source.metadata_json),
        "created_at": _serialize_datetime(source.created_at),
        "updated_at": _serialize_datetime(source.updated_at),
    }


def serialize_durable_memory_relation(relation: DurableMemoryRelation) -> dict[str, Any]:
    """Return a JSON-safe durable memory relation payload."""
    return {
        "relation_id": relation.id,
        "memory_id": relation.memory_id,
        "related_memory_id": relation.related_memory_id,
        "relation_type": relation.relation_type,
        "similarity_score": relation.similarity_score,
        "confidence": relation.confidence,
        "metadata_json": dict(relation.metadata_json),
        "created_at": _serialize_datetime(relation.created_at),
        "updated_at": _serialize_datetime(relation.updated_at),
    }


def serialize_durable_memory_audit_event(event: DurableMemoryAuditEvent) -> dict[str, Any]:
    """Return a JSON-safe durable memory audit event payload."""
    return {
        "event_id": event.id,
        "memory_id": event.memory_id,
        "job_id": event.job_id,
        "event_type": event.event_type,
        "from_status": event.from_status,
        "to_status": event.to_status,
        "reason_code": event.reason_code,
        "details_json": dict(event.details_json),
        "created_at": _serialize_datetime(event.created_at),
    }


def serialize_memory_projection_record(record: MemoryProjectionRecord) -> dict[str, Any]:
    """Return a JSON-safe memory projection record payload."""
    return {
        "projection_record_id": record.id,
        "collection_name": record.collection_name,
        "chroma_id": record.chroma_id,
        "record_key": record.record_key,
        "record_type": record.record_type,
        "memory_layer": record.memory_layer,
        "source_table": record.source_table,
        "source_id": record.source_id,
        "snapshot_id": record.snapshot_id,
        "quality_report_id": record.quality_report_id,
        "durable_memory_id": record.durable_memory_id,
        "claim_index": record.claim_index,
        "content_hash": record.content_hash,
        "embedding_model": record.embedding_model,
        "embedding_dimension": record.embedding_dimension,
        "status": record.status,
        "recall_visible": record.recall_visible,
        "relation_visible": record.relation_visible,
        "metadata_json": dict(record.metadata_json),
        "last_error": record.last_error,
        "indexed_at": _serialize_datetime(record.indexed_at),
        "created_at": _serialize_datetime(record.created_at),
        "updated_at": _serialize_datetime(record.updated_at),
    }


def _memory_rows() -> Select[tuple[DurableMemoryItem, MemorySession]]:
    return (
        select(DurableMemoryItem, MemorySession)
        .join(MemorySession)
        .options(
            selectinload(DurableMemoryItem.sources),
            selectinload(DurableMemoryItem.relations),
            selectinload(DurableMemoryItem.related_by_relations),
            selectinload(DurableMemoryItem.projection_records),
        )
    )


def _apply_memory_filters(
    query: Select,
    *,
    status: str | None,
    cwd: str | None,
    worktree_label: str | None,
    session_id: str | None,
) -> Select:
    if status is not None:
        query = query.where(DurableMemoryItem.status == status)
    if cwd is not None:
        query = query.where(MemorySession.cwd == cwd)
    if worktree_label is not None:
        query = query.where(MemorySession.worktree_label == worktree_label)
    if session_id is not None:
        query = query.where(MemorySession.session_id == session_id)
    return query


def _apply_projection_filters(
    query: Select,
    *,
    record_type: str | None,
    memory_layer: str | None,
    projection_status: str | None,
    recall_visible: bool | None,
    relation_visible: bool | None,
) -> Select:
    if record_type is not None:
        query = query.where(MemoryProjectionRecord.record_type == record_type)
    if memory_layer is not None:
        query = query.where(MemoryProjectionRecord.memory_layer == memory_layer)
    if projection_status is not None:
        query = query.where(MemoryProjectionRecord.status == projection_status)
    if recall_visible is not None:
        query = query.where(MemoryProjectionRecord.recall_visible == recall_visible)
    if relation_visible is not None:
        query = query.where(MemoryProjectionRecord.relation_visible == relation_visible)
    return query


def _validate_memory_filters(*, status: str | None, limit: int, offset: int) -> None:
    if status is not None and status not in DURABLE_MEMORY_STATUSES:
        raise DurableMemoryFilterError.invalid_status(status)
    _validate_pagination(limit=limit, offset=offset)


def _validate_projection_filters(
    *,
    record_type: str | None,
    memory_layer: str | None,
    projection_status: str | None,
    limit: int,
    offset: int,
) -> None:
    if record_type is not None and record_type not in MEMORY_PROJECTION_RECORD_TYPES:
        raise DurableMemoryFilterError.invalid_record_type(record_type)
    if memory_layer is not None and memory_layer not in MEMORY_LAYERS:
        raise DurableMemoryFilterError.invalid_memory_layer(memory_layer)
    if projection_status is not None and projection_status not in MEMORY_PROJECTION_STATUSES:
        raise DurableMemoryFilterError.invalid_projection_status(projection_status)
    _validate_pagination(limit=limit, offset=offset)


def _validate_pagination(*, limit: int, offset: int) -> None:
    if not 1 <= limit <= 100:
        raise DurableMemoryFilterError.invalid_limit()
    if offset < 0:
        raise DurableMemoryFilterError.invalid_offset()


def _query_payload(**values: Any) -> dict[str, Any]:
    return dict(values)


def _list_payload(
    *,
    results: list[dict[str, Any]],
    total: int,
    limit: int,
    offset: int,
    query: dict[str, Any],
) -> dict[str, Any]:
    return {
        "query": dict(query),
        "pagination": {
            "total": total,
            "returned": len(results),
            "limit": limit,
            "offset": offset,
        },
        "results": list(results),
    }


def _session_metadata(session: MemorySession) -> dict[str, Any]:
    return {
        "cwd": session.cwd,
        "worktree_label": session.worktree_label,
        "worktree_path": session.worktree_path,
    }


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
