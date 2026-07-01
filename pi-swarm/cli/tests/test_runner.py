from __future__ import annotations

import json
import os
import threading
from collections.abc import Sequence
from pathlib import Path

import pytest
from pi_swarm.frames import (
    PROTOCOL_VERSION,
    DispatchAckFrame,
    DispatchFrame,
    DispatchSpec,
    ListAgentsFrame,
    MessageStatusFrame,
    PeerMessageDeliveryAckFrame,
    PeerMessageDeliveryFrame,
    PeerMessageFrame,
    RegisterFrame,
    ResultReportFrame,
    TelemetryFrame,
    WaitFrame,
    WaitResultFrame,
    WaitResultItem,
    serialize_frame,
)
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
        agent_handle="amber-fox-a1b2c3",
        parent_session="session-1",
        agent_depth=1,
        result_path=tmp_path / "result.json",
    )


class FakeWebSocket:
    def __init__(self, messages: Sequence[str] = ()) -> None:
        self._messages = list(messages)
        self.sent: list[str] = []
        self.closed = False

    def recv(self) -> str:
        if not self._messages:
            raise EOFError
        return self._messages.pop(0)

    def send(self, message: str) -> None:
        self.sent.append(message)

    def close(self) -> None:
        self.closed = True


class UnexpectedDaemonRecvError(AssertionError):
    def __init__(self) -> None:
        super().__init__("daemon recv should not be called from child forwarding")


class NoRecvWebSocket(FakeWebSocket):
    def recv(self) -> str:
        raise UnexpectedDaemonRecvError


def _message(frame: object) -> str:
    return json.dumps(serialize_frame(frame))


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


def test_attempt_proxy_register_frame_preserves_child_session_name(tmp_path: Path) -> None:
    context = _context(tmp_path)
    proxy = AttemptDaemonProxy(context)
    child_register = RegisterFrame(
        type="register",
        v=PROTOCOL_VERSION,
        role="agent",
        node_id="child-node",
        agent_handle="amber-fox-a1b2c3",
        parent_id="parent-node",
        sibling_group="parent-node",
        depth=1,
        session_name="(scout) inspect auth [1a2b]",
        cwd="/repo",
    )

    register = proxy._register_frame(child_register)

    assert register.node_id == context.agent_id
    assert register.agent_handle == "amber-fox-a1b2c3"
    assert register.session_name == "(scout) inspect auth [1a2b]"
    assert register.session_name != context.agent_id


def test_attempt_proxy_forwards_rewritten_telemetry(tmp_path: Path) -> None:
    context = _context(tmp_path)
    proxy = AttemptDaemonProxy(context)
    child = FakeWebSocket(
        [
            _message(
                TelemetryFrame(
                    type="telemetry",
                    v=PROTOCOL_VERSION,
                    run_id="child-run",
                    agent_id="child-agent",
                    report_token="child-token",
                    kind="tool_call",
                    payload={"snippet": "bash echo hi"},
                )
            )
        ]
    )
    daemon = FakeWebSocket()

    proxy._forward_child_frames(child, daemon)

    assert len(daemon.sent) == 1
    forwarded = json.loads(daemon.sent[0])
    assert forwarded["type"] == "telemetry"
    assert forwarded["run_id"] == context.run_id
    assert forwarded["agent_id"] == context.agent_id
    assert forwarded["report_token"] == context.report_token
    assert forwarded["kind"] == "tool_call"
    assert forwarded["payload"] == {"snippet": "bash echo hi"}
    assert child.sent == []


def test_attempt_proxy_suppresses_result_report(tmp_path: Path) -> None:
    proxy = AttemptDaemonProxy(_context(tmp_path))
    child = FakeWebSocket(
        [
            _message(
                ResultReportFrame(
                    type="result_report",
                    v=PROTOCOL_VERSION,
                    run_id="run-1",
                    agent_id="agent-1",
                    report_token="token-1",
                    status="ok",
                    result="done",
                    error=None,
                    usage=None,
                )
            )
        ]
    )
    daemon = FakeWebSocket()

    proxy._forward_child_frames(child, daemon)

    assert daemon.sent == []
    assert child.sent == []


def test_attempt_proxy_forwards_dispatch_without_inline_daemon_recv(tmp_path: Path) -> None:
    proxy = AttemptDaemonProxy(_context(tmp_path))
    dispatch = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="ask-run-1",
        agent_id="ask-agent-1",
        agent_handle="amber-fox-a1b2c3",
        agent_type="ask",
        run_kind="ad-hoc",
        model="default",
        spec=DispatchSpec(
            argv=["pi", "answer this"],
            env={"BASECAMP_PROJECT": "proj"},
            cwd="/repo",
            resume_path=None,
            fork_from="target-agent",
            task="answer this",
        ),
    )
    child = FakeWebSocket([_message(dispatch)])
    daemon = NoRecvWebSocket()

    proxy._forward_child_frames(child, daemon)

    assert daemon.sent == [_message(dispatch)]
    assert child.sent == []


def test_attempt_proxy_forwards_dispatch_ack_from_daemon(tmp_path: Path) -> None:
    proxy = AttemptDaemonProxy(_context(tmp_path))
    dispatch_ack = DispatchAckFrame(
        type="dispatch_ack",
        v=PROTOCOL_VERSION,
        run_id="ask-run-1",
        status="spawned",
        reason=None,
    )
    child = FakeWebSocket()
    daemon = FakeWebSocket([_message(dispatch_ack)])

    proxy._forward_daemon_frames(daemon, child, threading.Event())

    assert child.sent == [_message(dispatch_ack)]


def test_attempt_proxy_forwards_wait_without_inline_daemon_recv(tmp_path: Path) -> None:
    proxy = AttemptDaemonProxy(_context(tmp_path))
    wait = WaitFrame(
        type="wait",
        v=PROTOCOL_VERSION,
        agent_handles=["amber-fox-a1b2c3"],
        mode="all",
        timeout_s=30,
    )
    child = FakeWebSocket([_message(wait)])
    daemon = NoRecvWebSocket()

    proxy._forward_child_frames(child, daemon)

    assert daemon.sent == [_message(wait)]
    assert child.sent == []


def test_attempt_proxy_forwards_wait_result_from_daemon(tmp_path: Path) -> None:
    proxy = AttemptDaemonProxy(_context(tmp_path))
    wait_result = WaitResultFrame(
        type="wait_result",
        v=PROTOCOL_VERSION,
        results=[
            WaitResultItem(
                agent_handle="amber-fox-a1b2c3",
                status="completed",
                result="answer",
                error=None,
            )
        ],
    )
    child = FakeWebSocket()
    daemon = FakeWebSocket([_message(wait_result)])

    proxy._forward_daemon_frames(daemon, child, threading.Event())

    assert child.sent == [_message(wait_result)]


def test_attempt_proxy_forwards_unsolicited_peer_message_delivery_from_daemon(tmp_path: Path) -> None:
    proxy = AttemptDaemonProxy(_context(tmp_path))
    delivery = PeerMessageDeliveryFrame(
        type="peer_message_delivery",
        v=PROTOCOL_VERSION,
        message_id="msg-1",
        from_handle="amber-fox-a1b2c3",
        from_relation="peer",
        message="hello from a peer",
        interrupt=True,
    )
    child = FakeWebSocket()
    daemon = FakeWebSocket([_message(delivery)])

    proxy._forward_daemon_frames(daemon, child, threading.Event())

    assert child.sent == [_message(delivery)]


def test_attempt_proxy_forwards_peer_client_frames_without_inline_daemon_recv(tmp_path: Path) -> None:
    proxy = AttemptDaemonProxy(_context(tmp_path))
    peer_message = PeerMessageFrame(
        type="peer_message",
        v=PROTOCOL_VERSION,
        request_id="request-1",
        target_handle="blue-wolf-d4e5f6",
        message="hello",
        interrupt=False,
    )
    message_status = MessageStatusFrame(
        type="message_status",
        v=PROTOCOL_VERSION,
        request_id="status-1",
        message_id="msg-1",
        wait_until_delivery=True,
        timeout_s=5,
    )
    delivery_ack = PeerMessageDeliveryAckFrame(
        type="peer_message_delivery_ack",
        v=PROTOCOL_VERSION,
        message_id="msg-1",
        status="queued",
        error=None,
    )
    list_agents = ListAgentsFrame(
        type="list_agents",
        v=PROTOCOL_VERSION,
        request_id="list-1",
        awaitable=True,
    )
    child = FakeWebSocket(
        [
            _message(peer_message),
            _message(message_status),
            _message(delivery_ack),
            _message(list_agents),
        ]
    )
    daemon = NoRecvWebSocket()

    proxy._forward_child_frames(child, daemon)

    assert daemon.sent == [
        _message(peer_message),
        _message(message_status),
        _message(delivery_ack),
        _message(list_agents),
    ]
    assert child.sent == []


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
