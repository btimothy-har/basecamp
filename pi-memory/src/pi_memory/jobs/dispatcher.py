"""Service-owned dispatcher for durable pi-memory jobs."""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from pi_memory.db import JOB_STATUS_CLAIMED, JOB_STATUS_RUNNING, Database, database
from pi_memory.jobs.store import JobStore, JobStoreError

DEFAULT_COMMAND = ("pi-memory",)
DEFAULT_LEASE_SECONDS = 60
DEFAULT_POLL_INTERVAL_SECONDS = 1.0


class ChildProcess(Protocol):
    """Small subprocess seam used by the dispatcher."""

    def wait(self, timeout: float | None = None) -> int:
        """Wait for process completion and return its exit code."""

    def poll(self) -> int | None:
        """Return the exit code if the process has exited, otherwise None."""

    def terminate(self) -> None:
        """Request process termination."""

    def kill(self) -> None:
        """Forcefully kill the process."""


ProcessFactory = Callable[[Sequence[str]], ChildProcess]
Clock = Callable[[], datetime]


class JobDispatcherError(RuntimeError):
    """Base class for dispatcher invariant errors."""


class ClaimedJobMissingRunIdError(JobDispatcherError):
    """Raised when a claimed job is missing its run token."""

    def __init__(self, job_id: int) -> None:
        super().__init__(f"Claimed job {job_id} is missing run_id")


class JobDispatcher:
    """Poll, claim, and dispatch jobs to one child process at a time."""

    def __init__(
        self,
        *,
        database: Database = database,
        store: JobStore | None = None,
        command: Sequence[str] = DEFAULT_COMMAND,
        process_factory: ProcessFactory | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        claimed_by: str | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._database = database
        self._store = JobStore(database=database) if store is None else store
        self._command = tuple(command)
        self._process_factory = _popen if process_factory is None else process_factory
        self._poll_interval = poll_interval
        self._lease_seconds = lease_seconds
        self._claimed_by = claimed_by or f"pi-memory-dispatcher-{uuid4()}"
        self._clock = _now if clock is None else clock
        self._stop_event = threading.Event()
        self._active_lock = threading.Lock()
        self._termination_lock = threading.Lock()
        self._active_process: ChildProcess | None = None
        self._thread: threading.Thread | None = None

    @property
    def is_alive(self) -> bool:
        """Return whether the dispatcher loop thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Recover stale work and start the dispatcher loop thread."""
        if self.is_alive:
            return
        self._stop_event.clear()
        self._store.recover_stale(now=self._clock())
        self._thread = threading.Thread(target=self._run_loop, name="pi-memory-job-dispatcher", daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        """Stop the dispatcher loop and terminate any active child process."""
        self._stop_event.set()
        self._terminate_active_process()

        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def run_once(self) -> bool:
        """Claim and run at most one due queued job.

        Returns True when a job was claimed, even if spawning or execution fails.
        Returns False when no due queued work is available.
        """
        if self._stop_event.is_set():
            return False

        job = self._store.claim_next(
            self._claimed_by,
            lease_seconds=self._lease_seconds,
            now=self._clock(),
        )
        if job is None:
            return False
        if job.run_id is None:
            raise ClaimedJobMissingRunIdError(job.id)

        argv = self._job_argv(job.id, job.run_id)
        try:
            process = self._process_factory(argv)
        except Exception as error:
            self._release_claim(job.id, job.run_id, f"Failed to spawn job child: {error}")
            return True

        with self._active_lock:
            self._active_process = process
        try:
            exit_code = self._wait_for_process(process)
        finally:
            with self._active_lock:
                if self._active_process is process:
                    self._active_process = None

        if exit_code != 0:
            self._record_child_failure(job.id, job.run_id, exit_code)
        return True

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            job_was_claimed = self.run_once()
            if not job_was_claimed:
                self._stop_event.wait(self._poll_interval)

    def _wait_for_process(self, process: ChildProcess) -> int:
        while True:
            try:
                return process.wait(timeout=self._poll_interval)
            except subprocess.TimeoutExpired:  # noqa: PERF203
                if self._stop_event.is_set():
                    self._terminate_active_process()

    def _job_argv(self, job_id: int, run_id: str) -> tuple[str, ...]:
        return (
            *self._command,
            "run-job",
            "--job-id",
            str(job_id),
            "--run-id",
            run_id,
            "--db-url",
            self._database.url,
        )

    def _release_claim(self, job_id: int, run_id: str, error: str) -> None:
        now = self._clock()
        self._store.release_claim(
            job_id,
            run_id,
            error=error,
            due_at=now + timedelta(seconds=self._poll_interval),
            now=now,
        )

    def _terminate_active_process(self) -> None:
        with self._termination_lock:
            with self._active_lock:
                process = self._active_process
            if process is not None:
                _terminate_process(process, timeout=self._poll_interval)

    def _record_child_failure(self, job_id: int, run_id: str, exit_code: int) -> None:
        job = self._store.get(job_id)
        if job is None or job.run_id != run_id:
            return

        error = f"Job child exited with code {exit_code}"
        if job.status == JOB_STATUS_CLAIMED:
            try:
                self._release_claim(job_id, run_id, error)
            except JobStoreError:
                current = self._store.get(job_id)
                if current is None or current.run_id != run_id or current.status != JOB_STATUS_RUNNING:
                    return
                self._fail_running_job(job_id, run_id, error, exit_code)
        elif job.status == JOB_STATUS_RUNNING:
            self._fail_running_job(job_id, run_id, error, exit_code)

    def _fail_running_job(self, job_id: int, run_id: str, error: str, exit_code: int) -> None:
        try:
            self._store.fail(job_id, run_id, error=error, exit_code=exit_code, retry=True, now=self._clock())
        except JobStoreError:
            return


def _popen(argv: Sequence[str]) -> ChildProcess:
    return subprocess.Popen(list(argv))


def _terminate_process(process: ChildProcess, *, timeout: float) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return


def _now() -> datetime:
    return datetime.now(UTC)
