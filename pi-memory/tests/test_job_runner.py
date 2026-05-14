from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pi_memory.db import (
    JOB_KIND_PROCESS_TRANSCRIPT,
    JOB_STATUS_CLAIMED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    Database,
    Job,
    MemorySession,
    Transcript,
    TranscriptEntry,
)
from pi_memory.jobs import (
    InvalidJobPayloadError,
    JobRunner,
    JobRunTokenMismatchError,
    JobStore,
    TranscriptNotFoundError,
    UnsupportedJobKindError,
)


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def database(tmp_path):
    database = Database(sqlite_url(tmp_path / "memory.db"))
    try:
        database.initialize()
        yield database
    finally:
        database.close_if_open()


@pytest.fixture
def store(database: Database) -> JobStore:
    return JobStore(database=database)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, tzinfo=UTC)


def create_transcript(database: Database) -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        transcript = Transcript(
            session=memory_session,
            path="/tmp/pi/transcript.jsonl",
            cursor_offset=200,
            file_size=250,
        )
        session.add(transcript)
        session.flush()
        session.add_all(
            [
                TranscriptEntry(
                    transcript_id=transcript.id,
                    entry_id="entry-1",
                    entry_type="message",
                    message_role="user",
                    raw_line='{"secret":"do not expose one"}',
                    byte_start=0,
                    byte_end=100,
                ),
                TranscriptEntry(
                    transcript_id=transcript.id,
                    entry_id="entry-2",
                    entry_type="message",
                    message_role="assistant",
                    raw_line='{"secret":"do not expose two"}',
                    byte_start=100,
                    byte_end=200,
                ),
            ],
        )
        session.flush()
        return transcript.id


def claim_process_transcript_job(store: JobStore, transcript_id: int | None = None, payload_json=None) -> Job:
    if payload_json is None:
        payload_json = {"transcript_id": transcript_id}
    store.enqueue(JOB_KIND_PROCESS_TRANSCRIPT, payload_json=payload_json, due_at=at(10))
    claimed = store.claim_next("worker-1", now=at(10))
    assert claimed is not None
    return claimed


def get_job(database: Database, job_id: int) -> Job:
    with database.session() as session:
        return session.get_one(Job, job_id)


def test_process_transcript_completes_and_writes_safe_result(database: Database, store: JobStore) -> None:
    transcript_id = create_transcript(database)
    claimed = claim_process_transcript_job(store, transcript_id)

    completed = JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    assert completed.status == JOB_STATUS_COMPLETED
    assert completed.attempts == 1
    assert completed.exit_code == 0
    assert completed.result_json == {
        "transcript_id": transcript_id,
        "session_id": "pi-session-1",
        "entry_count": 2,
        "cursor_offset": 200,
        "file_size": 250,
    }
    assert "do not expose" not in str(completed.result_json)


def test_wrong_run_id_is_rejected_without_incrementing_attempts(database: Database, store: JobStore) -> None:
    transcript_id = create_transcript(database)
    claimed = claim_process_transcript_job(store, transcript_id)

    with pytest.raises(JobRunTokenMismatchError):
        JobRunner(database=database).run(claimed.id, "wrong-run", now=at(10, 1))

    job = get_job(database, claimed.id)
    assert job.status == JOB_STATUS_CLAIMED
    assert job.attempts == 0


@pytest.mark.parametrize(
    ("payload_json", "expected_error"),
    [
        ({}, InvalidJobPayloadError),
        ({"transcript_id": "not-an-int"}, InvalidJobPayloadError),
        ({"transcript_id": 99999}, TranscriptNotFoundError),
    ],
)
def test_bad_process_transcript_data_terminal_fails_after_start(
    database: Database,
    store: JobStore,
    payload_json: dict[str, object],
    expected_error: type[Exception],
) -> None:
    claimed = claim_process_transcript_job(store, payload_json=payload_json)

    with pytest.raises(expected_error):
        JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    job = get_job(database, claimed.id)
    assert job.status == JOB_STATUS_FAILED
    assert job.attempts == 1
    assert job.exit_code == 1
    assert job.last_error


def test_unsupported_job_kind_terminal_fails_after_start(database: Database, store: JobStore) -> None:
    store.enqueue("unknown_kind", payload_json={}, due_at=at(10))
    claimed = store.claim_next("worker-1", now=at(10))
    assert claimed is not None

    with pytest.raises(UnsupportedJobKindError):
        JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    job = get_job(database, claimed.id)
    assert job.status == JOB_STATUS_FAILED
    assert job.attempts == 1
    assert job.exit_code == 1
    assert job.last_error == "Unsupported job kind: unknown_kind"
