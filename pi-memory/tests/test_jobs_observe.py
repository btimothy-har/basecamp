from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pi_memory.db import JOB_KIND_INTERPRET_SESSION, JOB_KIND_PROCESS_TRANSCRIPT, JOB_STATUS_QUEUED, Database, Job
from pi_memory.infra.job_queue import JobStore
from pi_memory.ingest import IngestResult
from pi_memory.pipeline.stages.process_transcript.enqueue import enqueue_process_transcript_job
from sqlalchemy import func, select


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def database(tmp_path):
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        yield database
    finally:
        database.close_if_open()


@pytest.fixture
def store(database: Database) -> JobStore:
    return JobStore(database=database)


def ingest_result(*, entries_ingested: int = 1) -> IngestResult:
    return IngestResult(
        session_id="pi-session-1",
        transcript_id=42,
        observation_id=7,
        entries_ingested=entries_ingested,
        cursor_offset=120,
        file_size=150,
        observed_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        malformed_lines=1,
        unsupported_lines=2,
    )


def test_enqueue_process_transcript_job_includes_audit_payload_without_raw_content(
    store: JobStore,
) -> None:
    result = ingest_result(entries_ingested=3)

    job = enqueue_process_transcript_job(store, result)

    assert job is not None
    assert job.kind == JOB_KIND_PROCESS_TRANSCRIPT
    assert job.status == JOB_STATUS_QUEUED
    assert job.payload_json == {
        "transcript_id": 42,
        "session_id": "pi-session-1",
        "observation_id": 7,
        "entries_ingested": 3,
        "cursor_offset": 120,
        "file_size": 150,
        "observed_at": "2026-01-01T12:00:00+00:00",
        "malformed_lines": 1,
        "unsupported_lines": 2,
    }
    assert "raw_line" not in job.payload_json
    assert "transcript content" not in str(job.payload_json)


def test_enqueue_process_transcript_job_returns_none_without_new_entries(
    database: Database,
    store: JobStore,
) -> None:
    job = enqueue_process_transcript_job(store, ingest_result(entries_ingested=0))

    assert job is None
    with database.session() as session:
        job_count = session.scalar(select(func.count()).select_from(Job))
        process_job_count = session.scalar(
            select(func.count()).select_from(Job).where(Job.kind == JOB_KIND_PROCESS_TRANSCRIPT),
        )
        interpret_job_count = session.scalar(
            select(func.count()).select_from(Job).where(Job.kind == JOB_KIND_INTERPRET_SESSION),
        )
    assert job_count == 0
    assert process_job_count == 0
    assert interpret_job_count == 0
