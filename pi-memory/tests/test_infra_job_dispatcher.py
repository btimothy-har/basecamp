from __future__ import annotations

import subprocess
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pi_memory.db import (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    Database,
    Job,
)
from pi_memory.infra.job_queue.store import JobStore, JobStoreError
from pi_memory.infra.job_runner import (
    BaseJob,
    ClaimedJobMissingRunIdError,
    JobDispatcher,
    JobExecutionContext,
    JobRegistry,
    JobRunner,
)


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


def get_job(database: Database, job_id: int) -> Job:
    with database.session() as session:
        return session.get_one(Job, job_id)


def db_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


def argv_value(argv: Sequence[str], option: str) -> str:
    return argv[argv.index(option) + 1]


def env_value(env: Mapping[str, str], name: str) -> str:
    return env[name]


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
        self.exit_code: int | None = None
        self.terminated = False
        self.killed = False

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


class RecordingJob(BaseJob):
    kind = "record"

    def run(self, context: JobExecutionContext, job: Job) -> dict[str, int]:
        _ = context
        return {"value": job.id}


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


class TemporaryStoreFailureError(JobStoreError):
    def __init__(self) -> None:
        super().__init__("temporary store failure")


class FailingOnceStore(JobStore):
    def __init__(self, database: Database) -> None:
        super().__init__(database=database)
        self.error_seen = threading.Event()
        self.continued = threading.Event()
        self.calls = 0

    def claim_next(
        self,
        claimed_by: str,
        lease_seconds: int = 60,
        now: datetime | None = None,
    ) -> Job | None:
        _ = claimed_by, lease_seconds, now
        self.calls += 1
        if self.calls == 1:
            self.error_seen.set()
            raise TemporaryStoreFailureError()
        self.continued.set()
        return None


class IgnoringTerminateProcess:
    def __init__(self) -> None:
        self.exit_code: int | None = None
        self.started = threading.Event()
        self._done = threading.Event()
        self.terminated = False
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        self.started.set()
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired(cmd="fake-child", timeout=timeout)
        assert self.exit_code is not None
        return self.exit_code

    def poll(self) -> int | None:
        return self.exit_code if self._done.is_set() else None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.exit_code = -9
        self._done.set()


def test_run_once_returns_false_and_does_not_spawn_when_queue_is_empty(
    database: Database,
    store: JobStore,
) -> None:
    spawned = False

    def process_factory(_argv: Sequence[str], _env: Mapping[str, str]) -> FakeProcess:
        nonlocal spawned
        spawned = True
        return FakeProcess()

    dispatcher = JobDispatcher(
        database=database,
        store=store,
        process_factory=process_factory,
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    assert dispatcher.run_once() is False
    assert spawned is False


def test_stop_prevents_run_once_and_keeps_job_queued(database: Database, store: JobStore) -> None:
    queued = store.enqueue("test", due_at=at(10))
    spawned = False

    def process_factory(_argv: Sequence[str], _env: Mapping[str, str]) -> FakeProcess:
        nonlocal spawned
        spawned = True
        return FakeProcess()

    dispatcher = JobDispatcher(
        database=database,
        store=store,
        process_factory=process_factory,
        poll_interval=0.01,
        clock=lambda: at(10),
    )
    dispatcher.stop(timeout=0.01)

    assert dispatcher.is_alive is False
    assert dispatcher.run_once() is False
    assert spawned is False

    released = get_job(database, queued.id)
    assert released.status == JOB_STATUS_QUEUED
    assert released.run_id is None


def test_run_once_claims_spawns_child_with_infra_job_env_and_runs_job(
    database: Database,
    store: JobStore,
) -> None:
    job = store.enqueue("record", due_at=at(10))
    captured_argv: list[str] = []
    captured_env: dict[str, str] = {}
    runner = JobRunner(database=database, store=store, registry=JobRegistry([RecordingJob()]))

    def process_factory(argv: Sequence[str], env: Mapping[str, str]) -> FakeProcess:
        captured_argv.extend(argv)
        captured_env.update(env)
        runner.run(
            int(argv_value(argv, "--job-id")),
            env_value(env, "PI_MEMORY_JOB_RUN_ID"),
            running_pid=123,
            now=at(10),
        )
        return FakeProcess(exit_code=0)

    dispatcher = JobDispatcher(
        database=database,
        store=store,
        process_factory=process_factory,
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    assert dispatcher.run_once() is True

    assert captured_argv[:2] == ["pi-memory", "run-job"]
    assert argv_value(captured_argv, "--job-id") == str(job.id)
    assert captured_env["PI_MEMORY_JOB_DB_URL"] == database.url
    assert captured_env["PI_MEMORY_JOB_RUN_ID"]

    completed = get_job(database, job.id)
    assert completed.status == JOB_STATUS_COMPLETED
    assert completed.result_json == {"value": job.id}


def test_spawn_failure_releases_claim_to_retry_after_poll_interval(
    database: Database,
    store: JobStore,
) -> None:
    job = store.enqueue("test", due_at=at(10))
    spawn_error = OSError("missing executable")

    def process_factory(_argv: Sequence[str], _env: Mapping[str, str]) -> FakeProcess:
        raise spawn_error

    dispatcher = JobDispatcher(
        database=database,
        store=store,
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


def test_child_exits_before_start_releases_claim(
    database: Database,
    store: JobStore,
) -> None:
    job = store.enqueue("test", due_at=at(10))

    dispatcher = JobDispatcher(
        database=database,
        store=store,
        process_factory=lambda _argv, _env: FakeProcess(exit_code=2),
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    assert dispatcher.run_once() is True

    released = get_job(database, job.id)
    assert released.status == JOB_STATUS_QUEUED
    assert released.attempts == 0
    assert released.run_id is None
    assert released.last_error == "Job child exited with code 2"
    assert released.due_at == db_datetime(at(10) + timedelta(seconds=0.01))


def test_child_starts_then_exits_nonzero_retries_running_job(
    database: Database,
    store: JobStore,
) -> None:
    job = store.enqueue("test", due_at=at(10), max_attempts=3)

    def process_factory(argv: Sequence[str], env: Mapping[str, str]) -> FakeProcess:
        store.start(
            int(argv_value(argv, "--job-id")),
            env_value(env, "PI_MEMORY_JOB_RUN_ID"),
            running_pid=123,
            now=at(10),
        )
        return FakeProcess(exit_code=7)

    dispatcher = JobDispatcher(
        database=database,
        store=store,
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


def test_child_nonzero_exhausts_to_failed_when_no_attempts_left(
    database: Database,
    store: JobStore,
) -> None:
    job = store.enqueue("test", due_at=at(10), max_attempts=1)

    def process_factory(argv: Sequence[str], env: Mapping[str, str]) -> FakeProcess:
        store.start(
            int(argv_value(argv, "--job-id")),
            env_value(env, "PI_MEMORY_JOB_RUN_ID"),
            running_pid=123,
            now=at(10),
        )
        return FakeProcess(exit_code=7)

    dispatcher = JobDispatcher(
        database=database,
        store=store,
        process_factory=process_factory,
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    assert dispatcher.run_once() is True

    failed = get_job(database, job.id)
    assert failed.status == JOB_STATUS_FAILED
    assert failed.attempts == 1
    assert failed.last_error == "Job child exited with code 7"
    assert failed.exit_code == 7
    assert failed.run_id is not None


def test_claimed_job_missing_run_id_raises_error(
    database: Database,
    store: JobStore,
) -> None:
    store.enqueue("test", due_at=at(10))

    dispatcher = JobDispatcher(
        database=database,
        store=MissingRunIdStore(database=database),
        process_factory=lambda _argv, _env: FakeProcess(exit_code=0),
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    with pytest.raises(ClaimedJobMissingRunIdError, match="Claimed job .* is missing run_id"):
        dispatcher.run_once()


def test_start_recovers_stale_running_job(database: Database, store: JobStore) -> None:
    original = store.enqueue("test", due_at=at(10), max_attempts=1)
    claimed = store.claim_next("worker-1", lease_seconds=1, now=at(10))
    assert claimed is not None
    store.start(claimed.id, claimed.run_id, lease_seconds=1, now=at(10))

    dispatcher = JobDispatcher(
        database=database,
        store=store,
        process_factory=lambda _argv, _env: FakeProcess(exit_code=0),
        poll_interval=0.01,
        clock=lambda: at(10, 0, 2),
    )

    dispatcher.start()
    dispatcher.stop(timeout=1)

    recovered = get_job(database, original.id)
    assert recovered.status == JOB_STATUS_FAILED
    assert recovered.last_error == "Job lease expired"


def test_start_and_stop_terminates_active_child(database: Database, store: JobStore) -> None:
    job = store.enqueue("test", due_at=at(10), max_attempts=3)
    process = BlockingProcess()
    process_created = threading.Event()

    def process_factory(argv: Sequence[str], env: Mapping[str, str]) -> BlockingProcess:
        store.start(
            int(argv_value(argv, "--job-id")),
            env_value(env, "PI_MEMORY_JOB_RUN_ID"),
            running_pid=123,
            now=at(10),
        )
        process_created.set()
        return process

    dispatcher = JobDispatcher(
        database=database,
        store=store,
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
    assert retried.exit_code == -15


def test_loop_continues_after_transient_store_error(
    database: Database,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = FailingOnceStore(database=database)
    dispatcher = JobDispatcher(
        database=database,
        store=store,
        process_factory=lambda _argv, _env: FakeProcess(exit_code=0),
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    dispatcher.start()
    assert store.error_seen.wait(timeout=1)
    assert store.continued.wait(timeout=1)
    dispatcher.stop(timeout=1)

    assert dispatcher.is_alive is False
    assert "Job dispatcher store error" in caplog.text
    assert "temporary store failure" in caplog.text


def test_claim_release_race_records_running_failure(
    database: Database,
    store: JobStore,
) -> None:
    job = store.enqueue("test", due_at=at(10), max_attempts=1)

    dispatcher = JobDispatcher(
        database=database,
        store=RacingReleaseStore(database=database),
        process_factory=lambda _argv, _env: FakeProcess(exit_code=9),
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    assert dispatcher.run_once() is True

    failed = get_job(database, job.id)
    assert failed.status == JOB_STATUS_FAILED
    assert failed.attempts == 1
    assert failed.last_error == "Job child exited with code 9"
    assert failed.exit_code == 9


def test_run_once_spawns_child_with_custom_command_prefix(
    database: Database,
    store: JobStore,
) -> None:
    job = store.enqueue("record", due_at=at(10))
    captured_argv: list[str] = []
    runner = JobRunner(database=database, store=store, registry=JobRegistry([RecordingJob()]))

    def process_factory(argv: Sequence[str], env: Mapping[str, str]) -> FakeProcess:
        captured_argv.extend(argv)
        runner.run(
            int(argv_value(argv, "--job-id")),
            env_value(env, "PI_MEMORY_JOB_RUN_ID"),
            running_pid=123,
            now=at(10),
        )
        return FakeProcess(exit_code=0)

    dispatcher = JobDispatcher(
        database=database,
        store=store,
        command=("pi-memory-subset", "--child"),
        process_factory=process_factory,
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    assert dispatcher.run_once() is True

    assert captured_argv[:3] == ["pi-memory-subset", "--child", "run-job"]
    assert argv_value(captured_argv, "--job-id") == str(job.id)

    completed = get_job(database, job.id)
    assert completed.status == JOB_STATUS_COMPLETED
    assert completed.result_json == {"value": job.id}


def test_stop_forces_kill_if_process_ignores_terminate(
    database: Database,
    store: JobStore,
) -> None:
    job = store.enqueue("test", due_at=at(10), max_attempts=1)
    process = IgnoringTerminateProcess()
    process_created = threading.Event()

    def process_factory(argv: Sequence[str], env: Mapping[str, str]) -> IgnoringTerminateProcess:
        store.start(
            int(argv_value(argv, "--job-id")),
            env_value(env, "PI_MEMORY_JOB_RUN_ID"),
            running_pid=123,
            now=at(10),
        )
        process_created.set()
        return process

    dispatcher = JobDispatcher(
        database=database,
        store=store,
        process_factory=process_factory,
        poll_interval=0.01,
        clock=lambda: at(10),
    )

    dispatcher.start()
    assert process_created.wait(timeout=1)
    assert process.started.wait(timeout=1)

    dispatcher.stop(timeout=1)

    assert process.terminated is True
    assert process.killed is True
    assert dispatcher.is_alive is False

    failed = get_job(database, job.id)
    assert failed.status == JOB_STATUS_FAILED
    assert failed.exit_code == -9
    assert failed.last_error == "Job child exited with code -9"
