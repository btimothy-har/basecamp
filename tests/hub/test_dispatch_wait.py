"""End-to-end wait semantics over dispatched runs."""

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

from basecamp.hub.frames import PROTOCOL_VERSION
from basecamp.hub.run_result import load_run_result, run_result_path
from basecamp.hub.store import Store

pytestmark = pytest.mark.usefixtures("_isolate_run_result_home")


def test_wait_empty_both_attempts_returns_runner_retry_failure(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-wait-empty-retry-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
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
                spec=_dispatch_spec(tmp_path, env={"FAKE_DAEMON_AGENT_MODE": "empty_both_attempts"}),
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
        assert wait_result["results"] == [
            {
                "agent_id": agent_id,
                "status": "failed",
                "result": None,
                "error": "empty_agent_result_after_retry",
            }
        ]

        run = store.get_run(run_id)
        assert run is not None
        assert run["status"] == "failed"
        assert run["error"] == "empty_agent_result_after_retry"

        sidecar = load_run_result(run_result_path(agent_id, run_id))
        assert sidecar is not None
        assert [attempt.result for attempt in sidecar.attempts] == ["", ""]
        assert sidecar.final is not None
        assert sidecar.final.error == "empty_agent_result_after_retry"
        assert sidecar.final.retry_count == 1
    finally:
        _stop_daemon(server, thread, uds_path)


def test_wait_all_happy_path_two_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-wait-all-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    run_id_1 = f"run-{uuid.uuid4()}"
    run_id_2 = f"run-{uuid.uuid4()}"
    agent_id_1 = f"agent-{uuid.uuid4()}"
    agent_id_2 = f"agent-{uuid.uuid4()}"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id="session-node", cwd=str(tmp_path))

            ack_1 = _dispatch(
                websocket,
                run_id=run_id_1,
                agent_id=agent_id_1,
                spec=_dispatch_spec(tmp_path, env={"FAKE_DAEMON_AGENT_SLEEP_MS": "150"}),
            )
            ack_2 = _dispatch(
                websocket,
                run_id=run_id_2,
                agent_id=agent_id_2,
                spec=_dispatch_spec(tmp_path, env={"FAKE_DAEMON_AGENT_SLEEP_MS": "50"}),
            )
            assert ack_1["status"] == "spawned"
            assert ack_2["status"] == "spawned"

            websocket.send(
                json.dumps(
                    {
                        "type": "wait",
                        "v": PROTOCOL_VERSION,
                        "agent_ids": [agent_id_1, agent_id_2],
                        "mode": "all",
                        "timeout_s": 5,
                    }
                )
            )
            wait_result = json.loads(websocket.recv())

        assert wait_result["type"] == "wait_result"
        results = {item["agent_id"]: item for item in wait_result["results"]}
        assert set(results) == {agent_id_1, agent_id_2}
        assert results[agent_id_1]["status"] == "completed"
        assert results[agent_id_2]["status"] == "completed"
    finally:
        _stop_daemon(server, thread, uds_path)


def test_wait_timeout_returns_running_status(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-wait-timeout-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
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
                    argv=[sys.executable, "-c", "import time; time.sleep(2)"],
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
                        "timeout_s": 0.1,
                    }
                )
            )
            wait_result = json.loads(websocket.recv())

        assert len(wait_result["results"]) == 1
        assert wait_result["results"][0]["agent_id"] == agent_id
        assert wait_result["results"][0]["status"] == "running"
        assert wait_result["results"][0]["result"] is None
        assert wait_result["results"][0]["error"] is None
    finally:
        _stop_daemon(server, thread, uds_path)


def test_wait_by_agent_handle_known_unknown_and_unauthorized(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-wait-handle-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as owner:
            _register_session(owner, node_id="owner", cwd=str(tmp_path))
            ack = _dispatch(
                owner,
                run_id="run-handle-owned",
                spec=_dispatch_spec(tmp_path),
                agent_id="agent-handle-owned",
                agent_handle="readable-owned",
            )
            assert ack["status"] == "spawned"

        deadline = time.time() + 10
        while time.time() < deadline:
            run = store.get_run("run-handle-owned")
            if run and run["status"] == "completed":
                break
            time.sleep(0.05)
        assert run is not None and run["status"] == "completed"

        with unix_connect(str(uds_path), uri="ws://localhost/ws") as owner:
            _register_session(owner, node_id="owner", cwd=str(tmp_path))
            owner.send(
                json.dumps(
                    {
                        "type": "wait",
                        "v": PROTOCOL_VERSION,
                        "agent_ids": [],
                        "agent_handles": ["readable-owned", "missing-handle"],
                        "mode": "all",
                        "timeout_s": 0.1,
                    }
                )
            )
            wait_result = json.loads(owner.recv())

        assert wait_result["results"][0]["agent_id"] == "agent-handle-owned"
        assert wait_result["results"][0]["agent_handle"] == "readable-owned"
        assert wait_result["results"][0]["status"] == "completed"
        assert wait_result["results"][1] == {
            "agent_handle": "missing-handle",
            "status": "unknown",
            "result": None,
            "error": None,
        }

        with unix_connect(str(uds_path), uri="ws://localhost/ws") as requester:
            _register_session(requester, node_id="other", cwd=str(tmp_path))
            requester.send(
                json.dumps(
                    {
                        "type": "wait",
                        "v": PROTOCOL_VERSION,
                        "agent_ids": [],
                        "agent_handles": ["readable-owned"],
                        "mode": "all",
                        "timeout_s": 0.1,
                    }
                )
            )
            unauthorized = json.loads(requester.recv())

        assert unauthorized["results"] == [
            {
                "agent_handle": "readable-owned",
                "status": "unknown",
                "result": None,
                "error": None,
            }
        ]
    finally:
        _stop_daemon(server, thread, uds_path)


def test_wait_unknown_handles_return_unknown_immediately(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-wait-unknown-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    unknown_agent_id = "agent-missing"
    start = time.time()

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id="session-node", cwd=str(tmp_path))
            websocket.send(
                json.dumps(
                    {
                        "type": "wait",
                        "v": PROTOCOL_VERSION,
                        "agent_ids": [unknown_agent_id],
                        "mode": "all",
                        "timeout_s": 10,
                    }
                )
            )
            wait_result = json.loads(websocket.recv())

        elapsed = time.time() - start
        assert elapsed < 2.0
        assert wait_result["type"] == "wait_result"
        assert wait_result["results"] == [
            {"agent_id": unknown_agent_id, "status": "unknown", "result": None, "error": None}
        ]
    finally:
        _stop_daemon(server, thread, uds_path)


def test_wait_by_non_dispatcher_returns_unknown_immediately(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-wait-acl-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    run_id = f"run-{uuid.uuid4()}"
    agent_id = f"agent-{uuid.uuid4()}"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as dispatcher:
            _register_session(dispatcher, node_id="dispatcher-node", cwd=str(tmp_path))
            ack = _dispatch(
                dispatcher,
                run_id=run_id,
                agent_id=agent_id,
                spec=_dispatch_spec(tmp_path, env={"FAKE_DAEMON_AGENT_SLEEP_MS": "1200"}),
            )
            assert ack["status"] == "spawned"

        start = time.time()
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as requester:
            _register_session(requester, node_id="other-node", cwd=str(tmp_path))
            requester.send(
                json.dumps(
                    {
                        "type": "wait",
                        "v": PROTOCOL_VERSION,
                        "agent_ids": [agent_id],
                        "mode": "all",
                        "timeout_s": 10,
                    }
                )
            )
            wait_result = json.loads(requester.recv())

        elapsed = time.time() - start
        assert elapsed < 2.0
        assert wait_result["results"] == [{"agent_id": agent_id, "status": "unknown", "result": None, "error": None}]
    finally:
        _stop_daemon(server, thread, uds_path)


def test_wait_mixed_unknown_and_completed_returns_all_handles(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-wait-mixed-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    run_id = f"run-{uuid.uuid4()}"
    agent_id = f"agent-{uuid.uuid4()}"
    unknown_agent_id = f"agent-{uuid.uuid4()}"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id="session-node", cwd=str(tmp_path))

            ack = _dispatch(
                websocket,
                run_id=run_id,
                agent_id=agent_id,
                spec=_dispatch_spec(
                    tmp_path,
                    env={"FAKE_DAEMON_AGENT_SLEEP_MS": "20"},
                ),
            )
            assert ack["status"] == "spawned"

            deadline = time.time() + 10
            while time.time() < deadline:
                run = store.get_run(run_id)
                if run and run["status"] == "completed":
                    break
                time.sleep(0.02)
            assert run is not None and run["status"] == "completed"

            websocket.send(
                json.dumps(
                    {
                        "type": "wait",
                        "v": PROTOCOL_VERSION,
                        "agent_ids": [agent_id, unknown_agent_id],
                        "mode": "all",
                        "timeout_s": 10,
                    }
                )
            )
            wait_result = json.loads(websocket.recv())

        assert [item["agent_id"] for item in wait_result["results"]] == [agent_id, unknown_agent_id]
        assert [item["status"] for item in wait_result["results"]] == ["completed", "unknown"]
    finally:
        _stop_daemon(server, thread, uds_path)
