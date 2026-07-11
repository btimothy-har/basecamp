"""End-to-end run reporting: backstop finalization and report-frame auth."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import pytest
from dispatch_helpers import (
    _dispatch,
    _dispatch_spec,
    _register_agent,
    _register_session,
    _start_daemon,
    _stop_daemon,
)
from websockets.sync.client import unix_connect

from basecamp.hub.frames import PROTOCOL_VERSION
from basecamp.hub.store import Store

pytestmark = pytest.mark.usefixtures("_isolate_run_result_home")


def test_backstop_marks_failed_and_resolves_wait(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-backstop-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    run_id = f"run-{uuid.uuid4()}"
    agent_id = f"agent-{uuid.uuid4()}"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id="session-node", cwd=str(tmp_path))

            ack = _dispatch(
                websocket,
                run_id=run_id,
                agent_id=agent_id,
                spec=_dispatch_spec(
                    tmp_path,
                    env={
                        "FAKE_DAEMON_AGENT_MODE": "no_result_exit",
                        "FAKE_DAEMON_AGENT_EXIT_CODE": "9",
                    },
                ),
            )
            assert ack["status"] == "spawned"

            websocket.send(
                json.dumps(
                    {
                        "type": "wait",
                        "v": PROTOCOL_VERSION,
                        "agent_ids": [agent_id],
                        "mode": "all",
                        "timeout_s": 5,
                    }
                )
            )
            wait_result = json.loads(websocket.recv())

        assert wait_result["type"] == "wait_result"
        assert len(wait_result["results"]) == 1
        item = wait_result["results"][0]
        assert item["agent_id"] == agent_id
        assert item["status"] == "failed"
        assert item["error"] == "agent_process_exited_code_9"

        run = store.get_run(run_id)
        assert run is not None
        assert run["status"] == "failed"
        assert run["error"] == "agent_process_exited_code_9"
    finally:
        _stop_daemon(server, thread, uds_path)


def test_dispatch_report_frames_accept_different_reporting_node_id(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-report-node-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    run_id = f"run-{uuid.uuid4()}"
    session_node = "session-node"
    provided_agent_id = f"agent-{uuid.uuid4()}"
    reporting_node = "report-node"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id=session_node, cwd=str(tmp_path))
            ack = _dispatch(
                websocket,
                run_id=run_id,
                spec=_dispatch_spec(
                    tmp_path,
                    env={
                        "FAKE_DAEMON_AGENT_NODE_ID": reporting_node,
                    },
                ),
                agent_id=provided_agent_id,
            )
            assert ack == {
                "type": "dispatch_ack",
                "v": PROTOCOL_VERSION,
                "run_id": run_id,
                "status": "spawned",
                "reason": None,
            }

        deadline = time.time() + 10
        run = None
        while time.time() < deadline:
            run = store.get_run(run_id)
            if run and run["status"] == "completed":
                break
            time.sleep(0.05)

        assert run is not None
        assert run["agent_id"] == provided_agent_id
        assert run["status"] == "completed"
        assert run["result"] == "fake-agent-result"
    finally:
        _stop_daemon(server, thread, uds_path)


def test_telemetry_and_invalid_result_reports_do_not_mutate_run(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-invalid-reports-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    run_id = f"run-{uuid.uuid4()}"
    token_path = tmp_path / f"{run_id}-token.txt"
    session_node = "session-node"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id=session_node, cwd=str(tmp_path))
            ack = _dispatch(
                websocket,
                run_id=run_id,
                spec=_dispatch_spec(
                    tmp_path,
                    env={
                        "FAKE_DAEMON_AGENT_MODE": "no_result_exit",
                        "FAKE_DAEMON_AGENT_EXIT_CODE": "9",
                        "FAKE_DAEMON_AGENT_SLEEP_MS": "1200",
                        "FAKE_DAEMON_AGENT_REPORT_TOKEN_PATH": str(token_path),
                    },
                ),
            )
            assert ack == {
                "type": "dispatch_ack",
                "v": PROTOCOL_VERSION,
                "run_id": run_id,
                "status": "spawned",
                "reason": None,
            }

        deadline = time.time() + 10
        run = None
        while time.time() < deadline:
            run = store.get_run(run_id)
            if run and run["status"] == "running":
                break
            time.sleep(0.05)

        assert run is not None
        assert run["status"] == "running"

        token = None
        while time.time() < deadline and token is None:
            if token_path.exists():
                token = token_path.read_text(encoding="utf-8").strip()
                break
            time.sleep(0.05)

        assert token
        run_agent_id = str(run["agent_id"])

        with unix_connect(str(uds_path), uri="ws://localhost/ws") as attacker:
            _register_agent(attacker, node_id="attacker-node", cwd=str(tmp_path))

            attacker.send(
                json.dumps(
                    {
                        "type": "telemetry",
                        "v": PROTOCOL_VERSION,
                        "run_id": run_id,
                        "agent_id": run_agent_id,
                        "report_token": "bad-token",
                        "kind": "tool_execution_end",
                        "payload": {"toolName": "x"},
                    }
                )
            )
            attacker.send(
                json.dumps(
                    {
                        "type": "telemetry",
                        "v": PROTOCOL_VERSION,
                        "run_id": run_id,
                        "agent_id": f"{run_agent_id}-wrong",
                        "report_token": token,
                        "kind": "tool_execution_end",
                        "payload": {"toolName": "y"},
                    }
                )
            )
            attacker.send(
                json.dumps(
                    {
                        "type": "result_report",
                        "v": PROTOCOL_VERSION,
                        "run_id": run_id,
                        "agent_id": f"{run_agent_id}-wrong",
                        "report_token": token,
                        "status": "ok",
                        "result": "attacker-result",
                        "error": None,
                        "usage": None,
                    }
                )
            )
            attacker.send(
                json.dumps(
                    {
                        "type": "result_report",
                        "v": PROTOCOL_VERSION,
                        "run_id": run_id,
                        "agent_id": run_agent_id,
                        "report_token": "bad-token",
                        "status": "ok",
                        "result": "attacker-result",
                        "error": None,
                        "usage": None,
                    }
                )
            )

        deadline = time.time() + 5
        while time.time() < deadline:
            run = store.get_run(run_id)
            if run and run["status"] == "failed":
                break
            time.sleep(0.05)

        assert run is not None
        assert run["status"] == "failed"
        assert run["result"] is None
        assert run["error"] == "agent_process_exited_code_9"
        assert run["result"] != "attacker-result"

        events = store.get_run_events(run_id)
        assert all(event["kind"] != "tool_execution_end" for event in events)
    finally:
        _stop_daemon(server, thread, uds_path)
