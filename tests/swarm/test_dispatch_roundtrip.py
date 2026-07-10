"""End-to-end dispatch spawn/result round-trip and child-env tests."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest
from dispatch_helpers import _dispatch, _dispatch_spec, _register_session, _start_daemon, _stop_daemon
from websockets.sync.client import unix_connect

from basecamp.swarm.frames import PROTOCOL_VERSION
from basecamp.swarm.run_result import load_run_result, run_result_path
from basecamp.swarm.store import Store

pytestmark = pytest.mark.usefixtures("_isolate_run_result_home")


def test_daemon_dispatch_spawn_and_result_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-dispatch-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    run_id = f"run-{uuid.uuid4()}"
    session_node = "session-node"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id=session_node, cwd=str(tmp_path))
            ack = _dispatch(websocket, run_id=run_id, spec=_dispatch_spec(tmp_path))
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
        assert run["status"] == "completed"
        assert run["result"] == "fake-agent-result"
        assert isinstance(run.get("report_token_hash"), str)
        assert run["report_token_hash"] != ""

        events = store.get_run_events(run_id)
        assert len(events) >= 1

        spec_json = run["spec_json"]
        assert isinstance(spec_json, dict)
        assert run["report_token_hash"] not in json.dumps(spec_json, sort_keys=True)

        agent_id = run["agent_id"]
        sidecar = load_run_result(run_result_path(agent_id, run_id))
        assert sidecar is not None
        assert len(sidecar.attempts) == 1
        assert sidecar.attempts[0].result == "fake-agent-result"
        assert sidecar.final is not None
        assert sidecar.final.result == "fake-agent-result"
        assert sidecar.final.retry_count == 0

        agent = store.get_agent(agent_id)
        assert agent is not None
        assert agent["depth"] == 1
        assert agent["parent_id"] == session_node
    finally:
        _stop_daemon(server, thread, uds_path)


def test_dispatch_stores_sanitized_spec_without_secret_values(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-dispatch-sanitized-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    run_id = f"run-{uuid.uuid4()}"
    session_node = "session-node"
    secret_env = {
        "OPENAI_API_KEY": "sk-openai-secret",
        "ANTHROPIC_API_KEY": "anthropic-secret",
        "CUSTOM_TOKEN": "token-secret",
        "PASSWORD": "db-password",
    }

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id=session_node, cwd=str(tmp_path))
            ack = _dispatch(websocket, run_id=run_id, spec=_dispatch_spec(tmp_path, env=secret_env))
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
        spec_json = run["spec_json"]
        assert isinstance(spec_json, dict)
        assert spec_json["argv"] == [sys.executable, str(Path(__file__).with_name("fake_daemon_agent.py"))]
        assert spec_json["cwd"] == str(tmp_path)
        assert spec_json["resume_path"] is None
        assert spec_json["task"] == "deterministic fake task"
        assert set(spec_json["env"]).issuperset(secret_env)
        assert spec_json.get("env_keys") == list(secret_env)
        assert all(value == "<redacted>" for value in spec_json["env"].values())

        serialized_spec = json.dumps(spec_json, sort_keys=True)
        assert "sk-openai-secret" not in serialized_spec
        assert "anthropic-secret" not in serialized_spec
        assert "token-secret" not in serialized_spec
        assert "db-password" not in serialized_spec
    finally:
        _stop_daemon(server, thread, uds_path)


def test_dispatch_uses_provided_agent_id_for_store_and_child_env(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-dispatch-provided-id-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    run_id = f"run-{uuid.uuid4()}"
    session_node = "session-node"
    provided_agent_id = f"agent-{uuid.uuid4()}"
    provided_agent_handle = "quiet-badger-3dc450"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id=session_node, cwd=str(tmp_path))
            ack = _dispatch(
                websocket,
                run_id=run_id,
                spec=_dispatch_spec(tmp_path, env={"FAKE_DAEMON_AGENT_RESULT_ENV_KEY": "BASECAMP_AGENT_HANDLE"}),
                agent_id=provided_agent_id,
                agent_handle=provided_agent_handle,
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
        assert run["status"] == "completed"
        assert run["agent_id"] == provided_agent_id
        assert run["result"] == f"fake-agent-result:BASECAMP_AGENT_HANDLE={provided_agent_handle}"

        agent = store.get_agent(provided_agent_id)
        assert agent is not None
        assert agent["id"] == provided_agent_id
        assert agent["agent_handle"] == provided_agent_handle
        assert agent["parent_id"] == session_node
    finally:
        _stop_daemon(server, thread, uds_path)


def test_dispatch_passes_full_env_to_spawned_child(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-dispatch-env-echo-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    run_id = f"run-{uuid.uuid4()}"
    session_node = "session-node"
    secret_api_key = "sk-openai-actual-value"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id=session_node, cwd=str(tmp_path))
            ack = _dispatch(
                websocket,
                run_id=run_id,
                spec=_dispatch_spec(
                    tmp_path,
                    env={
                        "OPENAI_API_KEY": secret_api_key,
                        "FAKE_DAEMON_AGENT_RESULT_ENV_KEY": "OPENAI_API_KEY",
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
            if run and run["status"] == "completed":
                break
            time.sleep(0.05)

        assert run is not None
        assert run["result"] == f"fake-agent-result:OPENAI_API_KEY={secret_api_key}"
    finally:
        _stop_daemon(server, thread, uds_path)


def test_dispatch_runner_managed_env_reaches_fake_child(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-dispatch-runner-env-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    run_id = f"run-{uuid.uuid4()}"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id="session-node", cwd=str(tmp_path))
            ack = _dispatch(
                websocket,
                run_id=run_id,
                spec=_dispatch_spec(
                    tmp_path,
                    env={"FAKE_DAEMON_AGENT_RESULT_ENV_KEY": "BASECAMP_RUNNER_MANAGED_RESULT"},
                ),
            )
            assert ack["status"] == "spawned"

        deadline = time.time() + 10
        run = None
        while time.time() < deadline:
            run = store.get_run(run_id)
            if run and run["status"] == "completed":
                break
            time.sleep(0.05)

        assert run is not None
        assert run["result"] == "fake-agent-result:BASECAMP_RUNNER_MANAGED_RESULT=1"
    finally:
        _stop_daemon(server, thread, uds_path)


def test_runner_managed_child_direct_result_report_is_suppressed(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-malicious-result-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    run_id = f"run-{uuid.uuid4()}"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id="session-node", cwd=str(tmp_path))
            ack = _dispatch(
                websocket,
                run_id=run_id,
                spec=_dispatch_spec(tmp_path, env={"FAKE_DAEMON_AGENT_MODE": "malicious_direct_result_report"}),
            )
            assert ack["status"] == "spawned"

        deadline = time.time() + 10
        run = None
        while time.time() < deadline:
            run = store.get_run(run_id)
            if run and run["status"] == "completed":
                break
            time.sleep(0.05)

        assert run is not None
        assert run["status"] == "completed"
        assert run["result"] == "fake-agent-result"
        assert run["result"] != "malicious-direct-result"
    finally:
        _stop_daemon(server, thread, uds_path)


def test_dispatch_empty_first_attempt_retries_and_recovers(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-dispatch-retry-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
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
                spec=_dispatch_spec(tmp_path, env={"FAKE_DAEMON_AGENT_MODE": "empty_first_attempt"}),
            )
            assert ack["status"] == "spawned"

        deadline = time.time() + 10
        run = None
        while time.time() < deadline:
            run = store.get_run(run_id)
            if run and run["status"] == "completed":
                break
            time.sleep(0.05)

        assert run is not None
        assert run["status"] == "completed"
        assert run["result"] == "fake-agent-result"

        sidecar = load_run_result(run_result_path(agent_id, run_id))
        assert sidecar is not None
        assert [attempt.result for attempt in sidecar.attempts] == ["", "fake-agent-result"]
        assert sidecar.final is not None
        assert sidecar.final.result == "fake-agent-result"
        assert sidecar.final.retry_count == 1
    finally:
        _stop_daemon(server, thread, uds_path)
