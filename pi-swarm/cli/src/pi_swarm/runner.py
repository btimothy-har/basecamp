"""Retry-capable runner for daemon-dispatched Pi attempts."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import secrets
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from pydantic import ValidationError

from .frames import (
    PROTOCOL_VERSION,
    RegisterFrame,
    ResultReportFrame,
    TelemetryFrame,
    parse_frame,
    serialize_frame,
)
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


class InvalidProxyFrameError(Exception):
    """Raised when an attempt proxy receives a malformed frame."""

    def __init__(self) -> None:
        super().__init__("Attempt proxy expected an object protocol frame.")


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


AttemptLauncher = Callable[[Sequence[str], int, Path, dict[str, str]], AttemptProcessResult]
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


def scrub_runner_process_env() -> None:
    os.environ.pop("BASECAMP_DAEMON_UDS", None)
    os.environ.pop("BASECAMP_REPORT_TOKEN", None)


def launch_attempt(
    command: Sequence[str],
    _attempt: int,
    _result_path: Path,
    child_env: dict[str, str],
) -> AttemptProcessResult:
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


class AttemptDaemonProxy:
    """Attempt-local UDS proxy that forwards telemetry but suppresses results."""

    def __init__(self, context: RunnerContext) -> None:
        self._context = context
        self._tempdir: tempfile.TemporaryDirectory[str] | None = None
        self._server: object | None = None
        self._thread: threading.Thread | None = None
        self.uds_path = ""

    def __enter__(self) -> AttemptDaemonProxy:
        self._tempdir = tempfile.TemporaryDirectory(prefix="basecamp-attempt-proxy-")
        self.uds_path = str(Path(self._tempdir.name) / "daemon.sock")
        websockets_server = importlib.import_module("websockets.sync.server")
        self._server = websockets_server.unix_serve(self._handle_connection, self.uds_path)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._wait_until_ready()
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if self._server is not None:
            self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._tempdir is not None:
            self._tempdir.cleanup()

    def _wait_until_ready(self) -> None:
        deadline = time.time() + 2
        while time.time() < deadline:
            if Path(self.uds_path).exists():
                return
            time.sleep(0.01)

    def _handle_connection(self, child_websocket: object) -> None:
        try:
            first = self._parse_next_frame(child_websocket)
            if not isinstance(first, RegisterFrame):
                return

            websockets_client = importlib.import_module("websockets.sync.client")
            with websockets_client.unix_connect(
                self._context.daemon_uds,
                uri="ws://localhost/ws",
            ) as daemon_websocket:
                daemon_websocket.send(json.dumps(serialize_frame(self._register_frame(first))))
                child_websocket.send(daemon_websocket.recv())
                self._forward_child_frames(child_websocket, daemon_websocket)
        except (OSError, EOFError, json.JSONDecodeError, ValidationError, InvalidProxyFrameError):
            return

    def _parse_next_frame(self, websocket: object) -> object:
        message = websocket.recv()
        payload = json.loads(message)
        if not isinstance(payload, dict):
            raise InvalidProxyFrameError
        return parse_frame(payload)

    def _register_frame(self, child_register: RegisterFrame) -> RegisterFrame:
        return RegisterFrame(
            type="register",
            v=PROTOCOL_VERSION,
            role="agent",
            node_id=self._context.agent_id,
            parent_id=self._context.parent_session,
            sibling_group=child_register.sibling_group,
            depth=self._context.agent_depth,
            session_name=self._context.agent_id,
            cwd=child_register.cwd,
        )

    def _forward_child_frames(self, child_websocket: object, daemon_websocket: object) -> None:
        while True:
            try:
                frame = self._parse_next_frame(child_websocket)
            except EOFError:
                return
            if isinstance(frame, TelemetryFrame):
                daemon_websocket.send(json.dumps(serialize_frame(self._telemetry_frame(frame))))
                continue
            if isinstance(frame, ResultReportFrame):
                continue
            return

    def _telemetry_frame(self, child_telemetry: TelemetryFrame) -> TelemetryFrame:
        return child_telemetry.model_copy(
            update={
                "run_id": self._context.run_id,
                "agent_id": self._context.agent_id,
                "report_token": self._context.report_token,
            }
        )


def attempt_env(
    context: RunnerContext,
    *,
    attempt: int,
    result_path: Path,
    proxy_uds: str,
) -> dict[str, str]:
    return {
        **os.environ,
        "BASECAMP_DAEMON_UDS": proxy_uds,
        "BASECAMP_REPORT_TOKEN": secrets.token_urlsafe(24),
        "BASECAMP_RUN_ID": context.run_id,
        "BASECAMP_AGENT_ID": context.agent_id,
        BASECAMP_RUNNER_MANAGED_RESULT: "1",
        BASECAMP_RUN_RESULT_PATH: str(result_path),
        BASECAMP_RUN_ATTEMPT: str(attempt),
    }


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
    with AttemptDaemonProxy(context) as proxy:
        process = attempt_launcher(
            command,
            attempt,
            context.result_path,
            attempt_env(
                context,
                attempt=attempt,
                result_path=context.result_path,
                proxy_uds=proxy.uds_path,
            ),
        )
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
    scrub_runner_process_env()

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
