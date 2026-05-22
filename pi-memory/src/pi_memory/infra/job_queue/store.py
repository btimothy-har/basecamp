"""Store for durable pi-memory job lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session

from pi_memory.db import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_CLAIMED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    Database,
    Job,
    database,
)

TERMINAL_STATUSES = {
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
}


class JobStoreError(RuntimeError):
    """Base class for job store errors."""


class JobNotFoundError(JobStoreError):
    """Raised when a requested job does not exist."""

    def __init__(self, job_id: int) -> None:
        super().__init__(f"Job {job_id} was not found")


class JobInvalidTransitionError(JobStoreError):
    """Raised when a job cannot move through the requested transition."""

    def __init__(self, job_id: int, operation: str) -> None:
        super().__init__(f"Job {job_id} cannot be transitioned by {operation}")


class JobRunTokenMismatchError(JobStoreError):
    """Raised when a transition is attempted with the wrong run token."""

    def __init__(self, job_id: int) -> None:
        super().__init__(f"Job {job_id} run token does not match")


class JobLeaseExpiredError(JobStoreError):
    """Raised when a claimed job lease expires before start."""

    def __init__(self, job_id: int) -> None:
        super().__init__(f"Job {job_id} claim lease has expired")


@dataclass(frozen=True)
class RecoverStaleResult:
    """Counts of jobs recovered from expired leases."""

    claimed_requeued: int = 0
    running_requeued: int = 0
    running_failed: int = 0


class JobStore:
    """Persist and transition durable background jobs."""

    def __init__(self, database: Database = database) -> None:
        self._database = database

    def enqueue(
        self,
        kind: str,
        payload_json: dict[str, Any] | None = None,
        priority: int = 0,
        due_at: datetime | None = None,
        max_attempts: int = 3,
        now: datetime | None = None,
    ) -> Job:
        """Create a queued job."""
        current_time = _coalesce_now(now)
        self._initialize()
        with self._database.session() as session:
            job = Job(
                kind=kind,
                payload_json={} if payload_json is None else payload_json,
                priority=priority,
                due_at=current_time if due_at is None else due_at,
                max_attempts=max_attempts,
            )
            session.add(job)
            session.flush()
            session.refresh(job)
            return job

    def claim_next(
        self,
        claimed_by: str,
        lease_seconds: int = 60,
        now: datetime | None = None,
    ) -> Job | None:
        """Atomically claim the next due queued job."""
        current_time = _coalesce_now(now)
        run_id = str(uuid4())
        lease_expires_at = current_time + timedelta(seconds=lease_seconds)
        self._initialize()
        with self._database.session() as session:
            next_job_id = (
                select(Job.id)
                .where(
                    Job.status == JOB_STATUS_QUEUED,
                    Job.due_at <= current_time,
                    Job.attempts < Job.max_attempts,
                )
                .order_by(Job.priority.asc(), Job.due_at.asc(), Job.created_at.asc())
                .limit(1)
                .scalar_subquery()
            )
            claimed_id = session.execute(
                update(Job)
                .where(Job.id == next_job_id)
                .values(
                    status=JOB_STATUS_CLAIMED,
                    run_id=run_id,
                    claimed_at=current_time,
                    claimed_by=claimed_by,
                    lease_expires_at=lease_expires_at,
                    updated_at=current_time,
                )
                .returning(Job.id),
            ).scalar_one_or_none()
            if claimed_id is None:
                return None
            return session.get_one(Job, claimed_id)

    def start(
        self,
        job_id: int,
        run_id: str,
        running_pid: int | None = None,
        lease_seconds: int = 60,
        now: datetime | None = None,
    ) -> Job:
        """Mark a claimed job as running and increment attempts once."""
        current_time = _coalesce_now(now)
        values = {
            "status": JOB_STATUS_RUNNING,
            "attempts": Job.attempts + 1,
            "started_at": current_time,
            "heartbeat_at": current_time,
            "lease_expires_at": current_time + timedelta(seconds=lease_seconds),
            "running_pid": running_pid,
            "updated_at": current_time,
        }
        return self._guarded_update(
            job_id=job_id,
            run_id=run_id,
            operation="start",
            required_status=JOB_STATUS_CLAIMED,
            values=values,
            extra_where=(Job.lease_expires_at > current_time,),
            current_time=current_time,
        )

    def heartbeat(
        self,
        job_id: int,
        run_id: str,
        lease_seconds: int = 60,
        now: datetime | None = None,
    ) -> Job:
        """Extend the active lease for a running job."""
        current_time = _coalesce_now(now)
        return self._guarded_update(
            job_id=job_id,
            run_id=run_id,
            operation="heartbeat",
            required_status=JOB_STATUS_RUNNING,
            values={
                "heartbeat_at": current_time,
                "lease_expires_at": current_time + timedelta(seconds=lease_seconds),
                "updated_at": current_time,
            },
        )

    def complete(
        self,
        job_id: int,
        run_id: str,
        result_json: dict[str, Any] | None = None,
        exit_code: int = 0,
        now: datetime | None = None,
    ) -> Job:
        """Mark a running job as completed."""
        current_time = _coalesce_now(now)
        return self._guarded_update(
            job_id=job_id,
            run_id=run_id,
            operation="complete",
            required_status=JOB_STATUS_RUNNING,
            values={
                "status": JOB_STATUS_COMPLETED,
                "finished_at": current_time,
                "exit_code": exit_code,
                "result_json": result_json,
                "lease_expires_at": None,
                "claimed_by": None,
                "running_pid": None,
                "updated_at": current_time,
            },
        )

    def fail(
        self,
        job_id: int,
        run_id: str,
        error: str,
        exit_code: int = 1,
        *,
        retry: bool = True,
        due_at: datetime | None = None,
        now: datetime | None = None,
    ) -> Job:
        """Fail a running job, optionally requeueing if attempts remain."""
        current_time = _coalesce_now(now)
        self._initialize()
        with self._database.session() as session:
            job = self._get_transition_job(session, job_id, run_id, JOB_STATUS_RUNNING, "fail")
            if retry and job.attempts < job.max_attempts:
                _requeue_job(job, due_at=current_time if due_at is None else due_at, now=current_time)
            else:
                job.status = JOB_STATUS_FAILED
                job.finished_at = current_time
                job.lease_expires_at = None
                job.claimed_by = None
                job.running_pid = None
            job.last_error = error
            job.exit_code = exit_code
            job.updated_at = current_time
            session.flush()
            session.refresh(job)
            return job

    def release_claim(
        self,
        job_id: int,
        run_id: str,
        error: str | None = None,
        due_at: datetime | None = None,
        now: datetime | None = None,
    ) -> Job:
        """Return a claimed job to the queue without incrementing attempts."""
        current_time = _coalesce_now(now)
        self._initialize()
        with self._database.session() as session:
            job = self._get_transition_job(session, job_id, run_id, JOB_STATUS_CLAIMED, "release_claim")
            _requeue_job(job, due_at=current_time if due_at is None else due_at, now=current_time)
            if error is not None:
                job.last_error = error
            session.flush()
            session.refresh(job)
            return job

    def cancel(self, job_id: int, now: datetime | None = None) -> Job:
        """Cancel a non-terminal job."""
        current_time = _coalesce_now(now)
        self._initialize()
        with self._database.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            if job.status in TERMINAL_STATUSES:
                raise JobInvalidTransitionError(job_id, "cancel")
            job.status = JOB_STATUS_CANCELLED
            job.finished_at = current_time
            job.run_id = None
            job.claimed_at = None
            job.claimed_by = None
            job.started_at = None
            job.heartbeat_at = None
            job.lease_expires_at = None
            job.running_pid = None
            job.updated_at = current_time
            session.flush()
            session.refresh(job)
            return job

    def recover_stale(self, now: datetime | None = None) -> RecoverStaleResult:
        """Recover claimed or running jobs whose leases have expired."""
        current_time = _coalesce_now(now)
        self._initialize()
        with self._database.session() as session:
            stale_jobs = list(
                session.scalars(
                    select(Job)
                    .where(
                        Job.status.in_([JOB_STATUS_CLAIMED, JOB_STATUS_RUNNING]),
                        Job.lease_expires_at <= current_time,
                    )
                    .order_by(Job.id.asc()),
                ),
            )
            claimed_requeued = 0
            running_requeued = 0
            running_failed = 0
            for job in stale_jobs:
                if job.status == JOB_STATUS_CLAIMED:
                    _requeue_job(job, due_at=current_time, now=current_time)
                    claimed_requeued += 1
                elif job.attempts < job.max_attempts:
                    # run_id/lease fencing is the durable truth; running_pid is observability-only.
                    _requeue_job(job, due_at=current_time, now=current_time)
                    running_requeued += 1
                else:
                    job.status = JOB_STATUS_FAILED
                    job.finished_at = current_time
                    job.lease_expires_at = None
                    job.claimed_by = None
                    job.running_pid = None
                    job.last_error = "Job lease expired"
                    job.updated_at = current_time
                    running_failed += 1
            return RecoverStaleResult(
                claimed_requeued=claimed_requeued,
                running_requeued=running_requeued,
                running_failed=running_failed,
            )

    def get(self, job_id: int) -> Job | None:
        """Return a job by id, if present."""
        self._initialize()
        with self._database.session() as session:
            return session.get(Job, job_id)

    def list_jobs(
        self,
        status: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[Job]:
        """List jobs with optional status and kind filters."""
        self._initialize()
        statement: Select[tuple[Job]] = select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(limit)
        if status is not None:
            statement = statement.where(Job.status == status)
        if kind is not None:
            statement = statement.where(Job.kind == kind)
        with self._database.session() as session:
            return list(session.scalars(statement))

    def _guarded_update(
        self,
        job_id: int,
        run_id: str,
        operation: str,
        required_status: str,
        values: dict[str, Any],
        extra_where: tuple[Any, ...] = (),
        current_time: datetime | None = None,
    ) -> Job:
        self._initialize()
        with self._database.session() as session:
            updated_id = session.execute(
                update(Job)
                .where(
                    Job.id == job_id,
                    Job.status == required_status,
                    Job.run_id == run_id,
                    *extra_where,
                )
                .values(**values)
                .returning(Job.id),
            ).scalar_one_or_none()
            if updated_id is None:
                self._raise_transition_error(session, job_id, run_id, required_status, operation, current_time)
            return session.get_one(Job, updated_id)

    def _get_transition_job(
        self,
        session: Session,
        job_id: int,
        run_id: str,
        required_status: str,
        operation: str,
    ) -> Job:
        job = session.get(Job, job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        if job.status != required_status:
            raise JobInvalidTransitionError(job_id, operation)
        if job.run_id != run_id:
            raise JobRunTokenMismatchError(job_id)
        return job

    def _raise_transition_error(
        self,
        session: Session,
        job_id: int,
        run_id: str,
        required_status: str,
        operation: str,
        current_time: datetime | None = None,
    ) -> None:
        job = session.get(Job, job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        if job.status != required_status:
            raise JobInvalidTransitionError(job_id, operation)
        if job.run_id != run_id:
            raise JobRunTokenMismatchError(job_id)
        if operation == "start" and current_time is not None and job.lease_expires_at is not None:
            lease_expires_at = job.lease_expires_at
            compare_time = current_time
            if lease_expires_at.tzinfo is None:
                lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
            if compare_time.tzinfo is None:
                compare_time = compare_time.replace(tzinfo=UTC)
            if lease_expires_at <= compare_time:
                raise JobLeaseExpiredError(job_id)
        raise JobInvalidTransitionError(job_id, operation)

    def _initialize(self) -> None:
        self._database.initialize()


def _now() -> datetime:
    return datetime.now(UTC)


def _coalesce_now(now: datetime | None) -> datetime:
    if now is None:
        return _now()
    return now


def _requeue_job(job: Job, due_at: datetime, now: datetime) -> None:
    job.status = JOB_STATUS_QUEUED
    job.due_at = due_at
    job.run_id = None
    job.claimed_at = None
    job.claimed_by = None
    job.started_at = None
    job.heartbeat_at = None
    job.lease_expires_at = None
    job.running_pid = None
    job.updated_at = now
