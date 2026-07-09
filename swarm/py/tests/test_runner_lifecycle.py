"""Runner attempt lifecycle: retries, exit codes, and final reports."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from basecamp.swarm.run_result import FinalRunResult, load_run_result
from basecamp.swarm.runner import (
    EMPTY_RESULT_AFTER_RETRY,
    RECOVERY_PROMPT,
    AttemptProcessResult,
    run,
)
from runner_helpers import _append_attempt, _context


def test_attempt_child_env_uses_proxy_socket_and_dummy_report_token(tmp_path: Path) -> None:
    context = _context(tmp_path)
    observed_envs: list[dict[str, str]] = []

    def launch(
        _command: Sequence[str],
        attempt: int,
        path: Path,
        env: dict[str, str],
    ) -> AttemptProcessResult:
        observed_envs.append(env)
        assert Path(env["BASECAMP_DAEMON_UDS"]).exists()
        _append_attempt(path, attempt=attempt, result="done")
        return AttemptProcessResult(exit_code=0)

    run(
        context,
        ["pi", "original task"],
        attempt_launcher=launch,
        report_sender=lambda _context, _final: None,
    )

    assert len(observed_envs) == 1
    child_env = observed_envs[0]
    assert child_env["BASECAMP_DAEMON_UDS"] != context.daemon_uds
    assert child_env["BASECAMP_REPORT_TOKEN"] != context.report_token
    assert child_env["BASECAMP_RUN_ID"] == context.run_id
    assert child_env["BASECAMP_AGENT_ID"] == context.agent_id


def test_non_empty_first_attempt_sends_one_ok_final_report_no_retry(tmp_path: Path) -> None:
    context = _context(tmp_path)
    reports: list[FinalRunResult] = []
    calls: list[tuple[list[str], int]] = []

    def launch(
        command: Sequence[str],
        attempt: int,
        path: Path,
        _env: dict[str, str],
    ) -> AttemptProcessResult:
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

    def launch(
        command: Sequence[str],
        attempt: int,
        path: Path,
        _env: dict[str, str],
    ) -> AttemptProcessResult:
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
    assert reports == [FinalRunResult(status="ok", result="recovered result", error=None, retry_count=1)]
    assert load_run_result(context.result_path).final == reports[0]


def test_empty_both_attempts_sends_error_report(tmp_path: Path) -> None:
    context = _context(tmp_path)
    reports: list[FinalRunResult] = []

    def launch(
        _command: Sequence[str],
        attempt: int,
        path: Path,
        _env: dict[str, str],
    ) -> AttemptProcessResult:
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

    def launch(
        _command: Sequence[str],
        attempt: int,
        path: Path,
        _env: dict[str, str],
    ) -> AttemptProcessResult:
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

    def launch(
        _command: Sequence[str],
        attempt: int,
        _path: Path,
        _env: dict[str, str],
    ) -> AttemptProcessResult:
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
