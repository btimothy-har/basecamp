from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import pytest
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
    AttemptDaemonProxy,
    AttemptProcessResult,
    ProxySocketUnavailableError,
    RunnerContext,
    run,
    scrub_runner_process_env,
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


def test_scrub_runner_process_env_removes_real_daemon_credentials(monkeypatch) -> None:
    monkeypatch.setenv("BASECAMP_DAEMON_UDS", "/tmp/real-daemon.sock")
    monkeypatch.setenv("BASECAMP_REPORT_TOKEN", "real-token")
    monkeypatch.setenv("BASECAMP_RUN_ID", "run-1")
    monkeypatch.setenv("BASECAMP_AGENT_ID", "agent-1")

    scrub_runner_process_env()

    assert "BASECAMP_DAEMON_UDS" not in os.environ
    assert "BASECAMP_REPORT_TOKEN" not in os.environ
    assert os.environ["BASECAMP_RUN_ID"] == "run-1"
    assert os.environ["BASECAMP_AGENT_ID"] == "agent-1"


def test_attempt_proxy_wait_until_ready_raises_when_socket_missing(tmp_path: Path, monkeypatch) -> None:
    proxy = AttemptDaemonProxy(_context(tmp_path))
    proxy.uds_path = str(tmp_path / "missing.sock")
    times = iter([0.0, 3.0])
    monkeypatch.setattr("pi_swarm.runner.time.time", lambda: next(times))
    monkeypatch.setattr("pi_swarm.runner.time.sleep", lambda _seconds: None)

    with pytest.raises(ProxySocketUnavailableError, match="failed to create socket"):
        proxy._wait_until_ready()


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
