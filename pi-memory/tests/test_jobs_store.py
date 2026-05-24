from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pi_memory.constants import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_CLAIMED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
)
from pi_memory.db.database import Database
from pi_memory.db.models import Job
from pi_memory.infra.job_queue import (
    JobInvalidTransitionError,
    JobLeaseExpiredError,
    JobRunTokenMismatchError,
    JobStore,
)


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def database(tmp_path):
    database = Database(sqlite_url(tmp_path / "memory.db"))
    try:
        yield database
    finally:
        database.close_if_open()


@pytest.fixture
def store(database: Database) -> JobStore:
    return JobStore(database=database)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, tzinfo=UTC)


def assert_same_time(actual: datetime | None, expected: datetime) -> None:
    assert actual is not None
    if actual.tzinfo is None:
        actual = actual.replace(tzinfo=UTC)
    assert actual == expected


def get_job(database: Database, job_id: int) -> Job:
    with database.session() as session:
        return session.get_one(Job, job_id)


def claim_job(
    store: JobStore,
    now: datetime | None = None,
    kind: str = "job",
    max_attempts: int = 3,
    lease_seconds: int = 120,
) -> Job:
    current_time = at(10) if now is None else now
    store.enqueue(kind, due_at=current_time, max_attempts=max_attempts)
    claimed = store.claim_next("worker-1", lease_seconds=lease_seconds, now=current_time)
    assert claimed is not None
    return claimed


def start_job(store: JobStore, now: datetime | None = None, kind: str = "job", max_attempts: int = 3) -> Job:
    current_time = at(10) if now is None else now
    claimed = claim_job(store, now=current_time, kind=kind, max_attempts=max_attempts)
    return store.start(claimed.id, claimed.run_id, now=current_time + timedelta(minutes=1))


def test_enqueue_defaults_and_explicit_fields(store: JobStore) -> None:
    now = at(8)
    default_job = store.enqueue("process_transcript", now=now)
    explicit_due_at = at(9)
    explicit_job = store.enqueue(
        "custom",
        payload_json={"session_id": "pi-session-1"},
        priority=2,
        due_at=explicit_due_at,
        max_attempts=5,
    )

    assert default_job.kind == "process_transcript"
    assert default_job.status == JOB_STATUS_QUEUED
    assert default_job.payload_json == {}
    assert default_job.idempotency_key is None
    assert default_job.priority == 0
    assert default_job.max_attempts == 3
    assert default_job.attempts == 0
    assert_same_time(default_job.due_at, now)
    assert explicit_job.kind == "custom"
    assert explicit_job.payload_json == {"session_id": "pi-session-1"}
    assert explicit_job.priority == 2
    assert explicit_job.max_attempts == 5
    assert_same_time(explicit_job.due_at, explicit_due_at)


def test_enqueue_returns_existing_job_for_idempotency_key(database: Database, store: JobStore) -> None:
    first = store.enqueue(
        "idempotent",
        payload_json={"attempt": 1},
        due_at=at(8),
        idempotency_key="summarize:1:interpret_session",
    )
    second = store.enqueue(
        "idempotent",
        payload_json={"attempt": 2},
        due_at=at(9),
        idempotency_key="summarize:1:interpret_session",
    )

    assert second.id == first.id
    assert second.payload_json == {"attempt": 1}
    assert second.idempotency_key == "summarize:1:interpret_session"
    assert_same_time(second.due_at, at(8))
    assert [job.id for job in store.list_jobs(kind="idempotent")] == [first.id]
    assert get_job(database, first.id).idempotency_key == "summarize:1:interpret_session"


def test_enqueue_without_idempotency_key_remains_append_only(store: JobStore) -> None:
    first = store.enqueue("repeat", due_at=at(8))
    second = store.enqueue("repeat", due_at=at(8))

    assert first.id != second.id
    assert {job.id for job in store.list_jobs(kind="repeat")} == {first.id, second.id}


def test_claim_next_claims_only_due_queued_job_without_incrementing_attempts(
    database: Database,
    store: JobStore,
) -> None:
    now = at(10)
    future_job = store.enqueue("future", due_at=now + timedelta(minutes=5))
    due_job = store.enqueue("due", due_at=now)

    claimed = store.claim_next("worker-1", lease_seconds=30, now=now)

    assert claimed is not None
    assert claimed.id == due_job.id
    assert claimed.status == JOB_STATUS_CLAIMED
    assert claimed.run_id is not None
    assert claimed.claimed_by == "worker-1"
    assert_same_time(claimed.claimed_at, now)
    assert_same_time(claimed.lease_expires_at, now + timedelta(seconds=30))
    assert claimed.attempts == 0
    assert get_job(database, future_job.id).status == JOB_STATUS_QUEUED


def test_claim_next_prioritizes_lower_priority_values(store: JobStore) -> None:
    now = at(10)
    store.enqueue("low-urgency", priority=5, due_at=now)
    high_urgency = store.enqueue("high-urgency", priority=1, due_at=now)
    store.enqueue("medium-urgency", priority=3, due_at=now)

    claimed = store.claim_next("worker-1", now=now)

    assert claimed is not None
    assert claimed.id == high_urgency.id


def test_claim_next_skips_exhausted_queued_jobs(database: Database, store: JobStore) -> None:
    now = at(10)
    exhausted = store.enqueue("exhausted", due_at=now, max_attempts=1)
    available = store.enqueue("available", due_at=now, max_attempts=1)
    with database.session() as session:
        job = session.get_one(Job, exhausted.id)
        job.attempts = job.max_attempts

    claimed = store.claim_next("worker-1", now=now)

    assert claimed is not None
    assert claimed.id == available.id
    assert get_job(database, exhausted.id).status == JOB_STATUS_QUEUED


def test_repeated_claims_claim_one_job_at_a_time_without_duplicates(store: JobStore) -> None:
    now = at(10)
    first = store.enqueue("first", priority=0, due_at=now)
    second = store.enqueue("second", priority=1, due_at=now)

    first_claim = store.claim_next("worker-1", now=now)
    second_claim = store.claim_next("worker-2", now=now)
    empty_claim = store.claim_next("worker-3", now=now)

    assert first_claim is not None
    assert second_claim is not None
    assert {first_claim.id, second_claim.id} == {first.id, second.id}
    assert first_claim.id != second_claim.id
    assert empty_claim is None


def test_start_rejects_wrong_run_id_and_status_and_increments_attempts_once(store: JobStore) -> None:
    future = store.enqueue("future", due_at=at(11))
    claimed = claim_job(store, now=at(10))

    with pytest.raises(JobInvalidTransitionError):
        store.start(future.id, "missing", now=at(10, 1))
    with pytest.raises(JobRunTokenMismatchError):
        store.start(claimed.id, "wrong-run", now=at(10, 1))

    still_claimed = store.get(claimed.id)
    assert still_claimed is not None
    assert still_claimed.attempts == 0
    running = store.start(claimed.id, claimed.run_id, running_pid=123, lease_seconds=90, now=at(10, 1))

    assert running.status == JOB_STATUS_RUNNING
    assert running.attempts == 1
    assert running.running_pid == 123
    assert_same_time(running.started_at, at(10, 1))
    assert_same_time(running.heartbeat_at, at(10, 1))
    assert_same_time(running.lease_expires_at, at(10, 1) + timedelta(seconds=90))
    with pytest.raises(JobInvalidTransitionError):
        store.start(claimed.id, claimed.run_id, now=at(10, 2))
    assert store.get(claimed.id).attempts == 1


def test_start_rejects_expired_claim_lease_without_incrementing_attempts(store: JobStore) -> None:
    claimed = claim_job(store, now=at(10), lease_seconds=30)

    with pytest.raises(JobLeaseExpiredError):
        store.start(claimed.id, claimed.run_id, now=at(10, 1))

    still_claimed = store.get(claimed.id)
    assert still_claimed is not None
    assert still_claimed.status == JOB_STATUS_CLAIMED
    assert still_claimed.attempts == 0


def test_heartbeat_complete_and_fail_reject_invalid_run_id_and_status(store: JobStore) -> None:
    running = start_job(store)
    queued = store.enqueue("queued", due_at=at(10))

    with pytest.raises(JobRunTokenMismatchError):
        store.heartbeat(running.id, "wrong-run", now=at(10, 2))
    with pytest.raises(JobInvalidTransitionError):
        store.heartbeat(queued.id, "missing", now=at(10, 2))
    with pytest.raises(JobRunTokenMismatchError):
        store.complete(running.id, "wrong-run", now=at(10, 2))
    with pytest.raises(JobInvalidTransitionError):
        store.complete(queued.id, "missing", now=at(10, 2))
    with pytest.raises(JobRunTokenMismatchError):
        store.fail(running.id, "wrong-run", "boom", now=at(10, 2))
    with pytest.raises(JobInvalidTransitionError):
        store.fail(queued.id, "missing", "boom", now=at(10, 2))

    heartbeat = store.heartbeat(running.id, running.run_id, lease_seconds=45, now=at(10, 2))
    assert_same_time(heartbeat.heartbeat_at, at(10, 2))
    assert_same_time(heartbeat.lease_expires_at, at(10, 2) + timedelta(seconds=45))
    completed = store.complete(running.id, running.run_id, result_json={"ok": True}, now=at(10, 3))
    assert completed.status == JOB_STATUS_COMPLETED
    assert completed.result_json == {"ok": True}
    assert completed.exit_code == 0
    assert_same_time(completed.finished_at, at(10, 3))
    assert completed.lease_expires_at is None


def test_release_claim_requeues_without_incrementing_attempts(store: JobStore) -> None:
    claimed = claim_job(store)

    with pytest.raises(JobRunTokenMismatchError):
        store.release_claim(claimed.id, "wrong-run", now=at(10, 1))

    released = store.release_claim(claimed.id, claimed.run_id, error="spawn failed", due_at=at(11), now=at(10, 1))

    assert released.status == JOB_STATUS_QUEUED
    assert released.attempts == 0
    assert released.run_id is None
    assert released.claimed_by is None
    assert released.claimed_at is None
    assert released.lease_expires_at is None
    assert released.last_error == "spawn failed"
    assert_same_time(released.due_at, at(11))


def test_fail_with_retry_false_terminal_fails_when_attempts_remain(store: JobStore) -> None:
    running = start_job(store, max_attempts=3)

    failed = store.fail(running.id, running.run_id, "permanent", retry=False, now=at(10, 2))

    assert failed.status == JOB_STATUS_FAILED
    assert failed.attempts == 1
    assert failed.last_error == "permanent"
    assert_same_time(failed.finished_at, at(10, 2))


def test_fail_requeues_when_attempts_remain_and_terminal_fails_when_exhausted(store: JobStore) -> None:
    retry_job = start_job(store)
    retry_result = store.fail(
        retry_job.id,
        retry_job.run_id,
        "temporary",
        exit_code=2,
        retry=True,
        due_at=at(11),
        now=at(10, 2),
    )

    assert retry_result.status == JOB_STATUS_QUEUED
    assert retry_result.attempts == 1
    assert retry_result.last_error == "temporary"
    assert retry_result.exit_code == 2
    assert retry_result.run_id is None
    assert retry_result.started_at is None
    assert_same_time(retry_result.due_at, at(11))

    terminal_seed = store.enqueue("terminal", max_attempts=1, due_at=at(10))
    terminal_claim = store.claim_next("worker-1", lease_seconds=120, now=at(10))
    assert terminal_claim is not None
    assert terminal_claim.id == terminal_seed.id
    terminal_running = store.start(terminal_claim.id, terminal_claim.run_id, now=at(10, 1))
    terminal_result = store.fail(terminal_running.id, terminal_running.run_id, "permanent", now=at(10, 2))

    assert terminal_result.status == JOB_STATUS_FAILED
    assert terminal_result.attempts == 1
    assert terminal_result.last_error == "permanent"
    assert terminal_result.exit_code == 1
    assert_same_time(terminal_result.finished_at, at(10, 2))


def test_recover_stale_handles_stale_claimed_and_running_jobs(store: JobStore) -> None:
    now = at(10)
    stale_claimed = claim_job(store, now=now, kind="claimed", lease_seconds=10)
    stale_running_retry = store.enqueue("running-retry", max_attempts=3, due_at=now)
    stale_running_failed = store.enqueue("running-failed", max_attempts=1, due_at=now)
    fresh = store.enqueue("fresh", due_at=now)

    retry_claim = store.claim_next("worker-1", lease_seconds=10, now=now)
    failed_claim = store.claim_next("worker-1", lease_seconds=10, now=now)
    fresh_claim = store.claim_next("worker-1", lease_seconds=60, now=now)
    assert retry_claim is not None and retry_claim.id == stale_running_retry.id
    assert failed_claim is not None and failed_claim.id == stale_running_failed.id
    assert fresh_claim is not None and fresh_claim.id == fresh.id
    retry_running = store.start(retry_claim.id, retry_claim.run_id, lease_seconds=10, now=now)
    failed_running = store.start(failed_claim.id, failed_claim.run_id, lease_seconds=10, now=now)
    fresh_running = store.start(fresh_claim.id, fresh_claim.run_id, lease_seconds=60, now=now)

    result = store.recover_stale(now=now + timedelta(seconds=11))

    assert result.claimed_requeued == 1
    assert result.running_requeued == 1
    assert result.running_failed == 1
    recovered_claimed = store.get(stale_claimed.id)
    assert recovered_claimed.status == JOB_STATUS_QUEUED
    assert recovered_claimed.attempts == 0
    assert recovered_claimed.run_id is None
    assert recovered_claimed.claimed_at is None
    assert recovered_claimed.claimed_by is None
    assert recovered_claimed.lease_expires_at is None
    recovered_running = store.get(retry_running.id)
    assert recovered_running.status == JOB_STATUS_QUEUED
    assert recovered_running.attempts == 1
    assert recovered_running.run_id is None
    assert recovered_running.claimed_at is None
    assert recovered_running.claimed_by is None
    assert recovered_running.started_at is None
    assert recovered_running.heartbeat_at is None
    assert recovered_running.lease_expires_at is None
    assert recovered_running.running_pid is None
    assert store.get(failed_running.id).status == JOB_STATUS_FAILED
    assert store.get(failed_running.id).attempts == 1
    assert store.get(fresh_running.id).status == JOB_STATUS_RUNNING


def test_cancel_cancels_non_terminal_jobs_and_rejects_terminal_jobs(store: JobStore) -> None:
    queued = store.enqueue("queued", due_at=at(15))
    claimed = claim_job(store, now=at(10), kind="claimed")
    running = start_job(store, now=at(11), kind="running")
    completed_running = start_job(store, now=at(12), kind="completed")
    completed = store.complete(completed_running.id, completed_running.run_id, now=at(12, 2))
    failed_running = start_job(store, now=at(13), kind="failed")
    failed = store.fail(failed_running.id, failed_running.run_id, "boom", retry=False, now=at(13, 2))

    cancelled_queued = store.cancel(queued.id, now=at(10, 1))
    cancelled_claimed = store.cancel(claimed.id, now=at(10, 2))
    cancelled_running = store.cancel(running.id, now=at(11, 2))

    assert cancelled_queued.status == JOB_STATUS_CANCELLED
    assert_same_time(cancelled_queued.finished_at, at(10, 1))
    assert cancelled_claimed.status == JOB_STATUS_CANCELLED
    assert cancelled_claimed.run_id is None
    assert cancelled_claimed.claimed_at is None
    assert cancelled_claimed.claimed_by is None
    assert cancelled_claimed.lease_expires_at is None
    assert cancelled_running.status == JOB_STATUS_CANCELLED
    assert cancelled_running.run_id is None
    assert cancelled_running.started_at is None
    assert cancelled_running.heartbeat_at is None
    assert cancelled_running.running_pid is None
    with pytest.raises(JobInvalidTransitionError):
        store.cancel(cancelled_queued.id, now=at(10, 3))
    with pytest.raises(JobInvalidTransitionError):
        store.cancel(completed.id, now=at(12, 3))
    with pytest.raises(JobInvalidTransitionError):
        store.cancel(failed.id, now=at(13, 3))


def test_get_and_list_filters_work(store: JobStore) -> None:
    first = store.enqueue("alpha", due_at=at(10))
    second = store.enqueue("beta", due_at=at(10))
    claimed = store.claim_next("worker-1", now=at(10))
    assert claimed is not None

    assert store.get(first.id).id == first.id
    assert store.get(99999) is None
    queued_jobs = store.list_jobs(status=JOB_STATUS_QUEUED)
    alpha_jobs = store.list_jobs(kind="alpha")
    claimed_beta_jobs = store.list_jobs(status=JOB_STATUS_CLAIMED, kind="beta")
    limited_jobs = store.list_jobs(limit=1)

    assert [job.id for job in queued_jobs] == [second.id]
    assert [job.id for job in alpha_jobs] == [first.id]
    assert [job.id for job in claimed_beta_jobs] == []
    assert len(limited_jobs) == 1


def test_list_jobs_filters_claimed_kind(store: JobStore) -> None:
    alpha = store.enqueue("alpha", due_at=at(10))
    store.enqueue("beta", due_at=at(10))
    claimed = store.claim_next("worker-1", now=at(10))

    assert claimed is not None
    assert claimed.id == alpha.id
    assert [job.id for job in store.list_jobs(status=JOB_STATUS_CLAIMED, kind="alpha")] == [alpha.id]
