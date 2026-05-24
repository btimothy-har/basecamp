"""Lightweight periodic scheduler for pipeline reconciliation."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from pi_memory.pipeline.reconciliation.contracts import ReconciliationReport, ReconciliationRunOptions
from pi_memory.pipeline.reconciliation.reconciler import Reconciler

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]


class PipelineReconciliationScheduler:
    """Run reconciliation scans on a fixed timer in a background thread."""

    def __init__(
        self,
        reconciler: Reconciler | None = None,
        interval_seconds: float = 30.0,
        clock: Clock | None = None,
        options: ReconciliationRunOptions | None = None,
    ) -> None:
        self._reconciler = Reconciler() if reconciler is None else reconciler
        self._interval_seconds = interval_seconds
        self._clock = _utcnow if clock is None else clock
        self._options = options
        self._stop_event = threading.Event()
        self._run_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def is_alive(self) -> bool:
        """Return whether the scheduler loop thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start the scheduler loop in a background thread."""
        if self.is_alive:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="pi-memory-pipeline-reconciliation-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        """Stop the scheduler loop and block until it exits."""
        self._stop_event.set()

        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def run_once(self) -> ReconciliationReport:
        """Run one reconciliation pass."""
        if not self._run_lock.acquire(blocking=False):
            return self._empty_report()
        try:
            if self._stop_event.is_set():
                return self._empty_report()
            return self._reconciler.run_once(self._run_options())
        finally:
            self._run_lock.release()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("Reconciliation scheduler pass failed")
            if self._stop_event.wait(self._interval_seconds):
                break

    def _run_options(self) -> ReconciliationRunOptions:
        if self._options is None:
            return ReconciliationRunOptions(
                enqueue_missing=True,
                as_of=self._clock(),
            )
        return self._options.model_copy(update={"as_of": self._clock()})

    def _empty_report(self) -> ReconciliationReport:
        return ReconciliationReport(as_of=self._clock())


def _utcnow() -> datetime:
    return datetime.now(UTC)
