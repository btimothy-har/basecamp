from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pi_memory.db import (
    JOB_STATUS_CLAIMED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    Database,
    Job,
)
from pi_memory.infra.job_queue.store import JobRunTokenMismatchError, JobStore
from pi_memory.infra.job_runner import BaseJob, JobExecutionContext, JobRegistry, JobRunner, PermanentJobError
from pi_memory.infra.job_runner.errors import UnsupportedJobKindError


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def database(tmp_path: Path) -> Database:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    try:
        yield database
    finally:
        database.close_if_open()


@pytest.fixture
def store(database: Database) -> JobStore:
    return JobStore(database=database)


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, second, tzinfo=UTC)


class RecordingJob(BaseJob):
    kind = "record"

    def __init__(self) -> None:
        self.calls: list[tuple[JobExecutionContext, Job]] = []

    def run(self, context: JobExecutionContext, job: Job) -> dict[str, int]:
        self.calls.append((context, job))
        return {"value": job.id}


class InvalidPayloadError(PermanentJobError):
    def __init__(self) -> None:
        super().__init__("invalid payload")


class TransientFailureError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("temporary outage")


class PermanentFailureJob(BaseJob):
    kind = "permanent-failure"

    def run(self, _context: JobExecutionContext, _job: Job) -> dict[str, object]:
        raise InvalidPayloadError()


class TransientFailureJob(BaseJob):
    kind = "transient-failure"

    def run(self, _context: JobExecutionContext, _job: Job) -> dict[str, object]:
        raise TransientFailureError()


def claim_job(store: JobStore, *, kind: str, now: datetime, max_attempts: int = 3) -> Job:
    store.enqueue(kind, due_at=now, max_attempts=max_attempts)
    claimed = store.claim_next("worker-1", now=now)
    assert claimed is not None
    return claimed


def get_job(database: Database, job_id: int) -> Job:
    with database.session() as session:
        return session.get_one(Job, job_id)


def test_run_executes_job_and_persists_result(database: Database, store: JobStore) -> None:
    recording_job = RecordingJob()
    claimed = claim_job(store, kind=recording_job.kind, now=at(10))
    runner = JobRunner(database=database, store=store, registry=JobRegistry([recording_job]))

    completed = runner.run(claimed.id, claimed.run_id, running_pid=123, now=at(10, 0, 1))

    persisted = get_job(database, claimed.id)
    assert completed.id == claimed.id
    assert completed.status == JOB_STATUS_COMPLETED
    assert completed.result_json == {"value": claimed.id}
    assert persisted.status == JOB_STATUS_COMPLETED
    assert persisted.exit_code == 0
    assert persisted.result_json == {"value": claimed.id}
    assert persisted.attempts == 1

    assert len(recording_job.calls) == 1
    captured_context, captured_job = recording_job.calls[0]
    assert captured_context == JobExecutionContext(database=database, store=store)
    assert captured_job.id == claimed.id
    assert captured_job.kind == recording_job.kind


def test_unsupported_job_kind_fails_terminal(database: Database, store: JobStore) -> None:
    claimed = claim_job(store, kind="unknown-kind", now=at(10))
    runner = JobRunner(database=database, store=store)

    with pytest.raises(UnsupportedJobKindError):
        runner.run(claimed.id, claimed.run_id, running_pid=123, now=at(10, 0, 1))

    failed = get_job(database, claimed.id)
    assert failed.status == JOB_STATUS_FAILED
    assert failed.attempts == 1
    assert failed.exit_code == 1
    assert failed.last_error == "Unsupported job kind: unknown-kind"


def test_wrong_run_token_bubbles_and_does_not_increment_attempts(database: Database, store: JobStore) -> None:
    claimed = claim_job(store, kind="record", now=at(10))
    runner = JobRunner(database=database, store=store, registry=JobRegistry([RecordingJob()]))

    with pytest.raises(JobRunTokenMismatchError):
        runner.run(claimed.id, "wrong-run", running_pid=123, now=at(10, 0, 1))

    untouched = get_job(database, claimed.id)
    assert untouched.status == JOB_STATUS_CLAIMED
    assert untouched.attempts == 0


def test_permanent_job_error_fails_terminal(database: Database, store: JobStore) -> None:
    failing_job = PermanentFailureJob()
    claimed = claim_job(store, kind=failing_job.kind, now=at(10))
    runner = JobRunner(database=database, store=store, registry=JobRegistry([failing_job]))

    with pytest.raises(PermanentJobError):
        runner.run(claimed.id, claimed.run_id, running_pid=123, now=at(10, 0, 1))

    failed = get_job(database, claimed.id)
    assert failed.status == JOB_STATUS_FAILED
    assert failed.attempts == 1
    assert failed.last_error == "invalid payload"
    assert failed.exit_code == 1


def test_exception_is_requeued_for_retry_when_attempts_remain(database: Database, store: JobStore) -> None:
    transient_job = TransientFailureJob()
    claimed = claim_job(store, kind=transient_job.kind, now=at(10), max_attempts=2)
    runner = JobRunner(database=database, store=store, registry=JobRegistry([transient_job]))

    with pytest.raises(TransientFailureError):
        runner.run(claimed.id, claimed.run_id, running_pid=123, now=at(10, 0, 1))

    retried = get_job(database, claimed.id)
    assert retried.status == JOB_STATUS_QUEUED
    assert retried.attempts == 1
    assert retried.last_error == "temporary outage"
    assert retried.exit_code == 1
    assert retried.run_id is None
