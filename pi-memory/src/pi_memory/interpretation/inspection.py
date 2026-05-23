"""Read-only session interpretation snapshot inspection helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from pi_memory.db.database import (
    Database,
    database,
)
from pi_memory.db.models import (
    MemorySession,
    SessionInterpretationSnapshot,
)


class SessionInterpretationInspectionService:
    """Inspect latest session interpretation snapshots by stable Pi session id."""

    def __init__(self, database: Database = database) -> None:
        self._database = database

    def get_by_session_id(self, session_id: str) -> dict[str, Any] | None:
        """Return a safe read-only payload for a session interpretation snapshot."""
        self._database.initialize()
        with self._database.session() as db_session:
            row = db_session.execute(
                select(SessionInterpretationSnapshot, MemorySession)
                .join(MemorySession, SessionInterpretationSnapshot.session_id == MemorySession.id)
                .where(MemorySession.session_id == session_id),
            ).one_or_none()
            if row is None:
                return None

            snapshot, memory_session = row
            return serialize_session_interpretation_snapshot(
                snapshot,
                stable_session_id=memory_session.session_id,
            )


def serialize_session_interpretation_snapshot(
    snapshot: SessionInterpretationSnapshot,
    *,
    stable_session_id: str,
) -> dict[str, Any]:
    """Return a JSON-safe inspection payload without raw transcript content."""
    return {
        "session_id": stable_session_id,
        "session_row_id": snapshot.session_id,
        "snapshot_id": snapshot.id,
        "transcript_id": snapshot.transcript_id,
        "analysis_run_id": snapshot.analysis_run_id,
        "job_id": snapshot.job_id,
        "status": snapshot.status,
        "blocked_reason": snapshot.blocked_reason,
        "analyzed_through_entry_id": snapshot.analyzed_through_entry_id,
        "analyzed_through_byte_offset": snapshot.analyzed_through_byte_offset,
        "origin_counts": dict(snapshot.origin_counts_json),
        "claim_source_activity_count": snapshot.claim_source_activity_count,
        "interpretation_json": dict(snapshot.interpretation_json),
        "citations_json": list(snapshot.citations_json),
        "episode_interpretation": _episode_interpretation_coverage(snapshot),
        "model_metadata": dict(snapshot.model_metadata_json),
        "prompt_version": snapshot.prompt_version,
        "schema_version": snapshot.schema_version,
        "created_at": _serialize_datetime(snapshot.created_at),
        "updated_at": _serialize_datetime(snapshot.updated_at),
    }


def _episode_interpretation_coverage(snapshot: SessionInterpretationSnapshot) -> dict[str, Any]:
    interpretation = snapshot.interpretation_json if isinstance(snapshot.interpretation_json, dict) else {}
    coverage = interpretation.get("aggregation")
    return dict(coverage) if isinstance(coverage, dict) else {}


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
