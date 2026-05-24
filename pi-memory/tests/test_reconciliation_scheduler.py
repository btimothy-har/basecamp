from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest
from pi_memory.pipeline.reconciliation import (
    PipelineReconciliationScheduler,
    ReconciliationReport,
    ReconciliationRunOptions,
)


def _as_time(hour: int, *, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, second, tzinfo=UTC)


class RecordingReconciler:
    def __init__(self, result: ReconciliationReport | None = None) -> None:
        self.result = result
        self.options: ReconciliationRunOptions | None = None
        self.call_count = 0
        self.call_lock = threading.Lock()

    def run_once(self, options: ReconciliationRunOptions | None = None) -> ReconciliationReport:
        with self.call_lock:
            self.call_count += 1
            self.options = options
        return self.result or ReconciliationReport(as_of=options.as_of)


class ReconciliationPassError(RuntimeError):
    """Raised by test reconciler to exercise scheduler exception handling."""

    def __init__(self) -> None:
        super().__init__("reconciliation failed")


class FlakyReconciler:
    def __init__(self, second_pass: threading.Event) -> None:
        self.calls = 0
        self.calls_lock = threading.Lock()
        self.second_pass = second_pass

    def run_once(self, options: ReconciliationRunOptions) -> ReconciliationReport:
        with self.calls_lock:
            self.calls += 1
            if self.calls == 2:
                self.second_pass.set()
            current_call = self.calls

        if current_call == 1:
            raise ReconciliationPassError()
        return ReconciliationReport(as_of=options.as_of)


def test_run_once_uses_scheduler_default_options_and_injected_clock() -> None:
    fixed_now = _as_time(12)
    reconciler = RecordingReconciler()
    scheduler = PipelineReconciliationScheduler(reconciler=reconciler, clock=lambda: fixed_now)

    report = scheduler.run_once()

    assert report.as_of == fixed_now
    assert reconciler.call_count == 1
    assert reconciler.options is not None
    assert reconciler.options.enqueue_missing is True
    assert reconciler.options.as_of == fixed_now


def test_start_is_idempotent_and_runs_immediately() -> None:
    start_signal = threading.Event()

    class SlowReconciler:
        def __init__(self) -> None:
            self.calls = 0

        def run_once(self, options: ReconciliationRunOptions) -> ReconciliationReport:
            self.calls += 1
            start_signal.set()
            return ReconciliationReport(as_of=options.as_of)

    reconciler = SlowReconciler()
    scheduler = PipelineReconciliationScheduler(reconciler=reconciler, interval_seconds=10.0)

    scheduler.start()
    assert scheduler.is_alive
    scheduler.start()
    assert start_signal.wait(timeout=1)
    scheduler.stop(timeout=1)

    assert scheduler.is_alive is False
    assert reconciler.calls == 1


def test_start_runs_immediately_and_stop_is_clean() -> None:
    start_signal = threading.Event()

    class SlowReconciler:
        def __init__(self) -> None:
            self.calls = 0

        def run_once(self, options: ReconciliationRunOptions) -> ReconciliationReport:
            self.calls += 1
            start_signal.set()
            return ReconciliationReport(as_of=options.as_of)

    reconciler = SlowReconciler()
    scheduler = PipelineReconciliationScheduler(reconciler=reconciler, interval_seconds=10.0)

    scheduler.start()
    assert start_signal.wait(timeout=1)
    scheduler.stop(timeout=1)

    assert scheduler.is_alive is False
    assert reconciler.calls >= 1


def test_loop_catches_exceptions_and_continues_to_next_pass(caplog: pytest.LogCaptureFixture) -> None:
    second_pass = threading.Event()
    reconciler = FlakyReconciler(second_pass)
    scheduler = PipelineReconciliationScheduler(reconciler=reconciler, interval_seconds=0.05)

    scheduler.start()
    assert second_pass.wait(timeout=1)
    scheduler.stop(timeout=1)

    assert reconciler.calls >= 2
    assert "Reconciliation scheduler pass failed" in caplog.text


def test_run_once_is_guarded_against_concurrent_overlap() -> None:
    entered_first_call = threading.Event()
    release_first_call = threading.Event()
    concurrent_calls = 0
    max_concurrent_calls = 0
    concurrency_guard = threading.Lock()

    class ConcurrentReconciler:
        def __init__(self) -> None:
            self.calls = 0

        def run_once(self, options: ReconciliationRunOptions) -> ReconciliationReport:
            nonlocal concurrent_calls, max_concurrent_calls
            with concurrency_guard:
                self.calls += 1
                concurrent_calls += 1
                max_concurrent_calls = max(max_concurrent_calls, concurrent_calls)
            entered_first_call.set()
            release_first_call.wait()
            with concurrency_guard:
                concurrent_calls -= 1
            return ReconciliationReport(as_of=options.as_of)

    reconciler = ConcurrentReconciler()
    scheduler = PipelineReconciliationScheduler(reconciler=reconciler, interval_seconds=10.0)

    first_call = threading.Thread(target=lambda: scheduler.run_once())
    second_call = threading.Thread(target=lambda: scheduler.run_once())

    first_call.start()
    assert entered_first_call.wait(timeout=1)
    second_call.start()
    release_first_call.set()

    first_call.join(timeout=1)
    second_call.join(timeout=1)

    assert max_concurrent_calls == 1
    assert reconciler.calls == 1
