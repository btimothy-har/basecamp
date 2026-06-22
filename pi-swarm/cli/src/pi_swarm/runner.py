"""Retry-capable runner for daemon-dispatched Pi attempts."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .frames import PROTOCOL_VERSION, RegisterFrame, ResultReportFrame, serialize_frame
from .run_result import (
    BASECAMP_RUN_ATTEMPT,
    BASECAMP_RUN_RESULT_PATH,
    BASECAMP_RUNNER_MANAGED_RESULT,
    FinalRunResult,
    RunResultAttempt,
    RunResultSidecar,
    find_run_result_attempt,
    load_run_result,
    set_final_run_result,
)

EMPTY_RESULT_AFTER_RETRY = "empty_agent_result_after_retry"
RECOVERY_PROMPT = (
    "The previous attempt completed the task but produced an empty final answer. "
    "Provide the final answer for the just-completed task. Do not perform extra work "
    "unless necessary to answer accurately."
)


@dataclass(frozen=True)
class RunnerContext:
    daemon_uds: str
    run_id: str
    report_token: str
    agent_id: str
    parent_session: str | None
    agent_depth: int
    result_path: Path


@dataclass(frozen=True)
class AttemptProcessResult:
    exit_code: int | None
    spawn_error: str | None = None


@dataclass(frozen=True)
class AttemptResult:
    process: AttemptProcessResult
    sidecar: RunResultSidecar | None
    attempt: RunResultAttempt | None


AttemptLauncher = Callable[[Sequence[str], int, Path], AttemptProcessResult]
ReportSender = Callable[[RunnerContext, FinalRunResult], None]


def parse_agent_depth(value: str | None) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def context_from_env(env: dict[str, str], result_path: Path) -> RunnerContext | None:
    daemon_uds = env.get("BASECAMP_DAEMON_UDS")
    run_id = env.get("BASECAMP_RUN_ID")
    report_token = env.get("BASECAMP_REPORT_TOKEN")
    agent_id = env.get("BASECAMP_AGENT_ID")
    if not daemon_uds or not run_id or not report_token or not agent_id:
        return None

    return RunnerContext(
        daemon_uds=daemon_uds,
        run_id=run_id,
        report_token=report_token,
        agent_id=agent_id,
        parent_session=env.get("BASECAMP_PARENT_SESSION"),
        agent_depth=parse_agent_depth(env.get("BASECAMP_AGENT_DEPTH")),
        result_path=result_path,
    )


def launch_attempt(command: Sequence[str], attempt: int, result_path: Path) -> AttemptProcessResult:
    child_env = {
        **os.environ,
        BASECAMP_RUNNER_MANAGED_RESULT: "1",
        BASECAMP_RUN_RESULT_PATH: str(result_path),
        BASECAMP_RUN_ATTEMPT: str(attempt),
    }
    try:
        completed = subprocess.run(
            command,
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError as error:
        return AttemptProcessResult(exit_code=None, spawn_error=str(error))
    return AttemptProcessResult(exit_code=completed.returncode)


def send_result_report(context: RunnerContext, final: FinalRunResult) -> None:
    register = RegisterFrame(
        type="register",
        v=PROTOCOL_VERSION,
        role="agent",
        node_id=context.agent_id,
        parent_id=context.parent_session,
        sibling_group=None,
        depth=context.agent_depth,
        session_name=context.agent_id,
        cwd=os.getcwd(),
    )
    report = ResultReportFrame(
        type="result_report",
        v=PROTOCOL_VERSION,
        run_id=context.run_id,
        agent_id=context.agent_id,
        report_token=context.report_token,
        status=final.status,
        result=final.result,
        error=final.error,
        usage=None,
    )

    websockets_client = importlib.import_module("websockets.sync.client")
    with websockets_client.unix_connect(context.daemon_uds, uri="ws://localhost/ws") as websocket:
        websocket.send(json.dumps(serialize_frame(register)))
        websocket.recv()
        websocket.send(json.dumps(serialize_frame(report)))


def run(
    context: RunnerContext,
    command: Sequence[str],
    *,
    attempt_launcher: AttemptLauncher = launch_attempt,
    report_sender: ReportSender = send_result_report,
) -> int:
    final = _run_to_final(context, command, attempt_launcher)
    set_final_run_result(
        context.result_path,
        run_id=context.run_id,
        agent_id=context.agent_id,
        final=final,
    )
    report_sender(context, final)
    return 0


def _run_to_final(
    context: RunnerContext,
    command: Sequence[str],
    attempt_launcher: AttemptLauncher,
) -> FinalRunResult:
    first = _run_attempt(context, command, 1, attempt_launcher)
    first_error = _terminal_error(first)
    if first_error is not None:
        return FinalRunResult(status="error", result=None, error=first_error, retry_count=0)

    first_result = first.attempt.result if first.attempt else None
    if _has_result(first_result):
        return FinalRunResult(status="ok", result=first_result, error=None, retry_count=0)

    retry_command = [*command[:-1], RECOVERY_PROMPT]
    second = _run_attempt(context, retry_command, 2, attempt_launcher)
    second_error = _terminal_error(second)
    if second_error is not None:
        return FinalRunResult(status="error", result=None, error=second_error, retry_count=1)

    second_result = second.attempt.result if second.attempt else None
    if _has_result(second_result):
        return FinalRunResult(status="ok", result=second_result, error=None, retry_count=1)

    return FinalRunResult(
        status="error",
        result=None,
        error=EMPTY_RESULT_AFTER_RETRY,
        retry_count=1,
    )


def _run_attempt(
    context: RunnerContext,
    command: Sequence[str],
    attempt: int,
    attempt_launcher: AttemptLauncher,
) -> AttemptResult:
    process = attempt_launcher(command, attempt, context.result_path)
    sidecar = load_run_result(context.result_path)
    sidecar_attempt = find_run_result_attempt(sidecar, attempt) if sidecar else None
    return AttemptResult(process=process, sidecar=sidecar, attempt=sidecar_attempt)


def _terminal_error(result: AttemptResult) -> str | None:
    if result.process.spawn_error is not None:
        return f"spawn_error: {result.process.spawn_error}"
    if result.process.exit_code != 0:
        return f"agent_process_exited_code_{result.process.exit_code}"
    if result.attempt is None:
        return "missing_run_result_attempt"
    if result.attempt.status == "error":
        return result.attempt.error or "agent_attempt_error"
    return None


def _has_result(result: str | None) -> bool:
    return result is not None and bool(result.strip())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a retry-managed Pi agent attempt.")
    parser.add_argument("--result-path", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = _normalize_command(args.command)
    if not command:
        return 2

    context = context_from_env(os.environ, args.result_path)
    if context is None:
        return 1

    try:
        return run(context, command)
    except OSError:
        return 1


def _normalize_command(command: Sequence[str]) -> list[str]:
    if command and command[0] == "--":
        return list(command[1:])
    return list(command)


if __name__ == "__main__":
    raise SystemExit(main())
