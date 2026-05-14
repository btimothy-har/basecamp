from __future__ import annotations

import subprocess
import threading
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pi_memory.db import (
    JOB_KIND_PROCESS_TRANSCRIPT,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    Database,
    Job,
    MemorySession,
    Transcript,
    TranscriptEntry,
)
from pi_memory.jobs import ClaimedJobMissingRunIdError, JobDispatcher, JobRunner, JobStore, JobStoreError


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


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, second, tzinfo=UTC)


def get_job(database: Database, job_id: int) -> Job:
    with database.session() as session:
        return session.get_one(Job, job_id)


def db_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


def create_transcript(database: Database) -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-dispatcher")
        transcript = Transcript(
            session=memory_session,
            path="/tmp/pi/dispatcher-transcript.jsonl",
            cursor_offset=50,
            file_size=50,
        )
        session.add(transcript)
        session.flush()
        session.add(
            TranscriptEntry(
                transcript_id=transcript.id,
                entry_id="dispatcher-entry-1",
                entry_type="message",
                message_role="user",
                raw_line='{"content":"hidden"}',
                byte_start=0,
                byte_end=50,
            ),
        )
        session.flush()
        return transcript.id


class FakeProcess:
    def __init__(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        self.terminated = False
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        _ = timeout
        return self.exit_code

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class BlockingProcess:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.done = threading.Event()
        self.terminated = False
        self.killed = False
        self.exit_code: int | None = None

    def wait(self, timeout: float | None = None) -> int:
        self.started.set()
        if not self.done.wait(timeout):
            raise subprocess.TimeoutExpired(cmd="fake-child", timeout=timeout)
        assert self.exit_code is not None
        return self.exit_code

    def poll(self) -> int | None:
        return self.exit_code if self.done.is_set() else None

    def terminate(self) -> None:
        self.terminated = True
        self.exit_code = -15
        self.done.set()

    def kill(self) -> None:
        self.killed = True
        self.exit_code = -9
        self.done.set()


def argv_value(argv: Sequence[str], option: str) -> str:
    return argv[argv.index(option) + 1]


def test_run_once_returns_false_and_does_not_spawn_when_queue_empty(database: Database) -> None:
    spawned = False

    def process_factory(_argv: Sequence[str]) -> FakeProcess:
        nonlocal spawned
        spawned = True
        return FakeProcess()

    dispatcher = JobDispatcher(
        database=database,
        process_factory=process_factory,
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    assert dispatcher.run_once() is False
    assert spawned is False


def test_stop_before_start_is_safe_and_run_once_returns_false_when_stopped(
    database: Database,
    store: JobStore,
) -> None:
    job = store.enqueue("test", due_at=at(10))
    spawned = False

    def process_factory(_argv: Sequence[str]) -> FakeProcess:
        nonlocal spawned
        spawned = True
        return FakeProcess()

    dispatcher = JobDispatcher(
        database=database,
        process_factory=process_factory,
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    dispatcher.stop(timeout=0.01)

    assert dispatcher.is_alive is False
    assert dispatcher.run_once() is False
    assert spawned is False
    queued = get_job(database, job.id)
    assert queued.status == JOB_STATUS_QUEUED
    assert queued.run_id is None


def test_run_once_claims_spawns_and_observes_child_completion(database: Database, store: JobStore) -> None:
    transcript_id = create_transcript(database)
    job = store.enqueue(
        JOB_KIND_PROCESS_TRANSCRIPT,
        payload_json={"transcript_id": transcript_id},
        due_at=at(10),
    )
    captured_argv: list[str] = []

    def process_factory(argv: Sequence[str]) -> FakeProcess:
        captured_argv.extend(argv)
        JobRunner(database=database).run(
            int(argv_value(argv, "--job-id")),
            argv_value(argv, "--run-id"),
            running_pid=123,
            now=at(10),
        )
        return FakeProcess(exit_code=0)

    dispatcher = JobDispatcher(
        database=database,
        process_factory=process_factory,
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    assert dispatcher.run_once() is True

    assert captured_argv[:2] == ["pi-memory", "run-job"]
    assert argv_value(captured_argv, "--job-id") == str(job.id)
    assert argv_value(captured_argv, "--db-url") == database.url
    completed = get_job(database, job.id)
    assert completed.status == JOB_STATUS_COMPLETED
    assert completed.attempts == 1
    assert completed.result_json == {
        "transcript_id": transcript_id,
        "session_id": "pi-session-dispatcher",
        "entry_count": 1,
        "cursor_offset": 50,
        "file_size": 50,
        "indexed_entry_count": 0,
    }


def test_spawn_failure_releases_claim_to_future_due_at_without_incrementing_attempts(
    database: Database,
    store: JobStore,
) -> None:
    job = store.enqueue("test", due_at=at(10))

    spawn_error = OSError("missing executable")

    def process_factory(_argv: Sequence[str]) -> FakeProcess:
        raise spawn_error

    dispatcher = JobDispatcher(
        database=database,
        process_factory=process_factory,
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    assert dispatcher.run_once() is True

    released = get_job(database, job.id)
    assert released.status == JOB_STATUS_QUEUED
    assert released.attempts == 0
    assert released.run_id is None
    assert released.due_at == db_datetime(at(10) + timedelta(seconds=0.01))
    assert released.last_error == "Failed to spawn job child: missing executable"


def test_child_exits_before_start_releases_claim_to_future_due_at_without_incrementing_attempts(
    database: Database,
    store: JobStore,
) -> None:
    job = store.enqueue("test", due_at=at(10))
    dispatcher = JobDispatcher(
        database=database,
        process_factory=lambda _argv: FakeProcess(exit_code=2),
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    assert dispatcher.run_once() is True

    released = get_job(database, job.id)
    assert released.status == JOB_STATUS_QUEUED
    assert released.attempts == 0
    assert released.run_id is None
    assert released.due_at == db_datetime(at(10) + timedelta(seconds=0.01))
    assert released.last_error == "Job child exited with code 2"


def test_child_starts_then_exits_nonzero_retries_running_job(database: Database, store: JobStore) -> None:
    job = store.enqueue("test", due_at=at(10), max_attempts=3)

    def process_factory(argv: Sequence[str]) -> FakeProcess:
        store.start(
            int(argv_value(argv, "--job-id")),
            argv_value(argv, "--run-id"),
            running_pid=123,
            now=at(10),
        )
        return FakeProcess(exit_code=7)

    dispatcher = JobDispatcher(
        database=database,
        process_factory=process_factory,
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    assert dispatcher.run_once() is True

    retried = get_job(database, job.id)
    assert retried.status == JOB_STATUS_QUEUED
    assert retried.attempts == 1
    assert retried.run_id is None
    assert retried.last_error == "Job child exited with code 7"
    assert retried.exit_code == 7


def test_exhausted_running_job_failure_marks_job_failed(database: Database, store: JobStore) -> None:
    job = store.enqueue("test", due_at=at(10), max_attempts=1)

    def process_factory(argv: Sequence[str]) -> FakeProcess:
        store.start(
            int(argv_value(argv, "--job-id")),
            argv_value(argv, "--run-id"),
            running_pid=123,
            now=at(10),
        )
        return FakeProcess(exit_code=7)

    dispatcher = JobDispatcher(
        database=database,
        process_factory=process_factory,
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    assert dispatcher.run_once() is True

    failed = get_job(database, job.id)
    assert failed.status == JOB_STATUS_FAILED
    assert failed.attempts == 1
    assert failed.run_id is not None
    assert failed.last_error == "Job child exited with code 7"
    assert failed.exit_code == 7


class MissingRunIdStore(JobStore):
    def claim_next(
        self,
        claimed_by: str,
        lease_seconds: int = 60,
        now: datetime | None = None,
    ) -> Job | None:
        job = super().claim_next(claimed_by, lease_seconds=lease_seconds, now=now)
        if job is not None:
            job.run_id = None
        return job


class RacingReleaseError(JobStoreError):
    def __init__(self) -> None:
        super().__init__("state changed")


class RacingReleaseStore(JobStore):
    def release_claim(
        self,
        job_id: int,
        run_id: str,
        error: str | None = None,
        due_at: datetime | None = None,
        now: datetime | None = None,
    ) -> Job:
        _ = error, due_at
        self.start(job_id, run_id, running_pid=456, now=now)
        raise RacingReleaseError


def test_claimed_job_missing_run_id_raises_invariant_error(database: Database, store: JobStore) -> None:
    store.enqueue("test", due_at=at(10))
    dispatcher = JobDispatcher(
        database=database,
        store=MissingRunIdStore(database=database),
        process_factory=lambda _argv: FakeProcess(exit_code=0),
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    with pytest.raises(ClaimedJobMissingRunIdError, match="Claimed job .* is missing run_id"):
        dispatcher.run_once()


def test_claim_release_race_records_running_failure(database: Database, store: JobStore) -> None:
    job = store.enqueue("test", due_at=at(10), max_attempts=1)
    dispatcher = JobDispatcher(
        database=database,
        store=RacingReleaseStore(database=database),
        process_factory=lambda _argv: FakeProcess(exit_code=9),
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    assert dispatcher.run_once() is True

    failed = get_job(database, job.id)
    assert failed.status == JOB_STATUS_FAILED
    assert failed.attempts == 1
    assert failed.last_error == "Job child exited with code 9"
    assert failed.exit_code == 9


def test_start_recovers_stale_jobs_before_loop(database: Database, store: JobStore) -> None:
    store.enqueue("test", due_at=at(10), max_attempts=1)
    claimed = store.claim_next("worker-1", lease_seconds=1, now=at(10))
    assert claimed is not None
    running = store.start(claimed.id, claimed.run_id, lease_seconds=1, now=at(10))

    dispatcher = JobDispatcher(
        database=database,
        process_factory=lambda _argv: FakeProcess(exit_code=0),
        poll_interval=0.01,
        clock=lambda: at(10, 0, 2),
    )
    dispatcher.start()
    dispatcher.stop(timeout=1)

    recovered = get_job(database, running.id)
    assert recovered.status == JOB_STATUS_FAILED
    assert recovered.last_error == "Job lease expired"


def test_start_stop_lifecycle_exits_and_terminates_active_child(database: Database, store: JobStore) -> None:
    job = store.enqueue("test", due_at=at(10), max_attempts=3)
    process = BlockingProcess()
    process_created = threading.Event()

    def process_factory(argv: Sequence[str]) -> BlockingProcess:
        store.start(
            int(argv_value(argv, "--job-id")),
            argv_value(argv, "--run-id"),
            running_pid=123,
            now=at(10),
        )
        process_created.set()
        return process

    dispatcher = JobDispatcher(
        database=database,
        process_factory=process_factory,
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    dispatcher.start()
    assert process_created.wait(timeout=1)
    assert process.started.wait(timeout=1)

    dispatcher.stop(timeout=1)

    assert dispatcher.is_alive is False
    assert process.terminated is True
    retried = get_job(database, job.id)
    assert retried.status == JOB_STATUS_QUEUED
    assert retried.attempts == 1
    assert retried.last_error == "Job child exited with code -15"


def test_run_once_ignores_future_jobs(database: Database, store: JobStore) -> None:
    store.enqueue("future", due_at=at(10) + timedelta(minutes=5))
    spawned = False

    def process_factory(_argv: Sequence[str]) -> FakeProcess:
        nonlocal spawned
        spawned = True
        return FakeProcess()

    dispatcher = JobDispatcher(
        database=database,
        process_factory=process_factory,
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    assert dispatcher.run_once() is False
    assert spawned is False
