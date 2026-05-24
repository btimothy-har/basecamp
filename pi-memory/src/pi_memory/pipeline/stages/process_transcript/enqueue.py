"""Queue input contract for transcript processing jobs."""

from __future__ import annotations

from pi_memory.constants import (
    JOB_KIND_PROCESS_TRANSCRIPT,
    STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
    STRUCTURAL_LIVENESS_POLICY_VERSION,
)
from pi_memory.db.models import Job
from pi_memory.infra.job_queue.store import JobStore
from pi_memory.ingest import IngestResult
from pi_memory.pipeline.reconciliation.contracts import EnqueueSpec


def process_transcript_idempotency_key(
    *,
    transcript_id: int,
    analyzed_through_entry_id: int | None,
    analyzed_through_byte_offset: int,
    parent_transcript_path: str | None,
    parent_transcript_id: int | None,
    structural_analysis_schema_version: int = STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
    liveness_policy_version: int = STRUCTURAL_LIVENESS_POLICY_VERSION,
) -> str:
    """Build a deterministic idempotency key for structural transcript processing."""
    return (
        f"{JOB_KIND_PROCESS_TRANSCRIPT}:{transcript_id}:"
        f"{analyzed_through_entry_id or 0}:{analyzed_through_byte_offset}:"
        f"{parent_transcript_path or ''}:{parent_transcript_id or 0}:"
        f"schema-v{structural_analysis_schema_version}:"
        f"liveness-v{liveness_policy_version}"
    )


def process_transcript_job_spec_from_fields(
    *,
    transcript_id: int,
    analyzed_through_entry_id: int | None,
    analyzed_through_byte_offset: int,
    parent_transcript_path: str | None,
    parent_transcript_id: int | None,
    structural_analysis_schema_version: int = STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
    liveness_policy_version: int = STRUCTURAL_LIVENESS_POLICY_VERSION,
    idempotency_key: str | None = None,
) -> EnqueueSpec:
    """Build the enqueue spec for structural transcript processing repair."""
    return EnqueueSpec(
        kind=JOB_KIND_PROCESS_TRANSCRIPT,
        payload_json={
            "transcript_id": transcript_id,
            "analyzed_through_entry_id": analyzed_through_entry_id,
            "analyzed_through_byte_offset": analyzed_through_byte_offset,
            "parent_transcript_path": parent_transcript_path,
            "parent_transcript_id": parent_transcript_id,
            "structural_analysis_schema_version": structural_analysis_schema_version,
            "liveness_policy_version": liveness_policy_version,
        },
        idempotency_key=idempotency_key,
    )


def process_transcript_job_spec(result: IngestResult) -> EnqueueSpec | None:
    """Build the enqueue spec for transcript processing."""
    if result.entries_ingested == 0:
        return None

    return EnqueueSpec(
        kind=JOB_KIND_PROCESS_TRANSCRIPT,
        payload_json={
            "transcript_id": result.transcript_id,
            # Remaining fields are audit/debug context for inspecting queued work.
            # The runner uses SQLite as truth and only requires transcript_id.
            "session_id": result.session_id,
            "observation_id": result.observation_id,
            "entries_ingested": result.entries_ingested,
            "cursor_offset": result.cursor_offset,
            "file_size": result.file_size,
            "observed_at": result.observed_at.isoformat(),
            "malformed_lines": result.malformed_lines,
            "unsupported_lines": result.unsupported_lines,
        },
    )


def enqueue_process_transcript_job(store: JobStore, result: IngestResult) -> Job | None:
    """Enqueue transcript processing for an ingest result with new entries."""
    spec = process_transcript_job_spec(result)
    if spec is None:
        return None
    return store.enqueue(**spec.model_dump())
