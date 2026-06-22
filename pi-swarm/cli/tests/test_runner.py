from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pi_swarm.run_result import (
    FinalRunResult,
    RunResultAttempt,
    RunResultSidecar,
    RunResultStatus,
    load_run_result,
    write_run_result,
)
from pi_swarm.runner import (
    EMPTY_RESULT_AFTER_RETRY,
    RECOVERY_PROMPT,
    AttemptProcessResult,
    RunnerContext,
    run,
)


def _context(tmp_path: Path) -> RunnerContext:
    return RunnerContext(
        daemon_uds=str(tmp_path / "daemon.sock"),
        run_id="run-1",
        report_token="token-1",
        agent_id="agent-1",
        parent_session="session-1",
        agent_depth=1,
        result_path=tmp_path / "result.json",
    )


def _append_attempt(
    path: Path,
    *,
    attempt: int,
    status: RunResultStatus = "ok",
    result: str | None,
    error: str | None = None,
) -> None:
    sidecar = load_run_result(path) or RunResultSidecar(
        run_id="run-1",
        agent_id="agent-1",
        attempts=[],
        final=None,
    )
    sidecar.attempts.append(
        RunResultAttempt(
            attempt=attempt,
            status=status,
            result=result,
            error=error,
        )
    )
    write_run_result(path, sidecar)


def test_non_empty_first_attempt_sends_one_ok_final_report_no_retry(tmp_path: Path) -> None:
    context = _context(tmp_path)
    reports: list[FinalRunResult] = []
    calls: list[tuple[list[str], int]] = []

    def launch(command: Sequence[str], attempt: int, path: Path) -> AttemptProcessResult:
        calls.append((list(command), attempt))
        _append_attempt(path, attempt=attempt, result="done")
        return AttemptProcessResult(exit_code=0)

    exit_code = run(
        context,
        ["pi", "original task"],
        attempt_launcher=launch,
        report_sender=lambda _context, final: reports.append(final),
    )

    assert exit_code == 0
    assert calls == [(["pi", "original task"], 1)]
    assert reports == [FinalRunResult(status="ok", result="done", error=None, retry_count=0)]
    assert load_run_result(context.result_path).final == reports[0]


def test_empty_first_attempt_then_non_empty_retry_sends_ok_report(tmp_path: Path) -> None:
    context = _context(tmp_path)
    reports: list[FinalRunResult] = []
    calls: list[tuple[list[str], int]] = []

    def launch(command: Sequence[str], attempt: int, path: Path) -> AttemptProcessResult:
        calls.append((list(command), attempt))
        result = "  " if attempt == 1 else "recovered result"
        _append_attempt(path, attempt=attempt, result=result)
        return AttemptProcessResult(exit_code=0)

    exit_code = run(
        context,
        ["pi", "--model", "fast", "original task"],
        attempt_launcher=launch,
        report_sender=lambda _context, final: reports.append(final),
    )

    assert exit_code == 0
    assert calls == [
        (["pi", "--model", "fast", "original task"], 1),
        (["pi", "--model", "fast", RECOVERY_PROMPT], 2),
    ]
    assert reports == [
        FinalRunResult(status="ok", result="recovered result", error=None, retry_count=1)
    ]
    assert load_run_result(context.result_path).final == reports[0]


def test_empty_both_attempts_sends_error_report(tmp_path: Path) -> None:
    context = _context(tmp_path)
    reports: list[FinalRunResult] = []

    def launch(_command: Sequence[str], attempt: int, path: Path) -> AttemptProcessResult:
        _append_attempt(path, attempt=attempt, result="")
        return AttemptProcessResult(exit_code=0)

    exit_code = run(
        context,
        ["pi", "original task"],
        attempt_launcher=launch,
        report_sender=lambda _context, final: reports.append(final),
    )

    assert exit_code == 0
    assert reports == [
        FinalRunResult(
            status="error",
            result=None,
            error=EMPTY_RESULT_AFTER_RETRY,
            retry_count=1,
        )
    ]
    assert load_run_result(context.result_path).final == reports[0]


def test_nonzero_child_exit_does_not_retry_and_sends_error_report(tmp_path: Path) -> None:
    context = _context(tmp_path)
    reports: list[FinalRunResult] = []
    calls: list[int] = []

    def launch(_command: Sequence[str], attempt: int, path: Path) -> AttemptProcessResult:
        calls.append(attempt)
        _append_attempt(path, attempt=attempt, result="done")
        return AttemptProcessResult(exit_code=7)

    exit_code = run(
        context,
        ["pi", "original task"],
        attempt_launcher=launch,
        report_sender=lambda _context, final: reports.append(final),
    )

    assert exit_code == 0
    assert calls == [1]
    assert reports == [
        FinalRunResult(
            status="error",
            result=None,
            error="agent_process_exited_code_7",
            retry_count=0,
        )
    ]


def test_missing_sidecar_attempt_does_not_retry_and_sends_error_report(tmp_path: Path) -> None:
    context = _context(tmp_path)
    reports: list[FinalRunResult] = []
    calls: list[int] = []

    def launch(_command: Sequence[str], attempt: int, _path: Path) -> AttemptProcessResult:
        calls.append(attempt)
        return AttemptProcessResult(exit_code=0)

    exit_code = run(
        context,
        ["pi", "original task"],
        attempt_launcher=launch,
        report_sender=lambda _context, final: reports.append(final),
    )

    assert exit_code == 0
    assert calls == [1]
    assert reports == [
        FinalRunResult(
            status="error",
            result=None,
            error="missing_run_result_attempt",
            retry_count=0,
        )
    ]
    sidecar = load_run_result(context.result_path)
    assert sidecar is not None
    assert sidecar.attempts == []
    assert sidecar.final == reports[0]
