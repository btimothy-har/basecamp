"""End-to-end dispatch acceptance policy: rejections and depth caps."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import pytest
from dispatch_helpers import _dispatch, _dispatch_spec, _register_session, _start_daemon, _stop_daemon
from websockets.sync.client import unix_connect

from basecamp.swarm.frames import PROTOCOL_VERSION
from basecamp.swarm.store import Store

pytestmark = pytest.mark.usefixtures("_isolate_run_result_home")


def test_dispatch_rejects_second_active_primary_run_for_agent(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-dispatch-active-run-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    agent_id = f"agent-{uuid.uuid4()}"
    first_run_id = f"run-{uuid.uuid4()}"
    second_run_id = f"run-{uuid.uuid4()}"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id="session-node", cwd=str(tmp_path))
            first_ack = _dispatch(
                websocket,
                run_id=first_run_id,
                agent_id=agent_id,
                spec=_dispatch_spec(tmp_path, env={"FAKE_DAEMON_AGENT_SLEEP_MS": "1200"}),
            )
            second_ack = _dispatch(
                websocket,
                run_id=second_run_id,
                agent_id=agent_id,
                spec=_dispatch_spec(tmp_path),
            )

        assert first_ack["status"] == "spawned"
        assert second_ack == {
            "type": "dispatch_ack",
            "v": PROTOCOL_VERSION,
            "run_id": second_run_id,
            "status": "rejected",
            "reason": "active_run_exists",
        }
        assert store.get_run(second_run_id) is None
    finally:
        _stop_daemon(server, thread, uds_path)


def test_dispatch_rejects_duplicate_agent_handle(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-duplicate-handle-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    store.upsert_agent(
        agent_id="agent-1",
        agent_handle="existing-handle",
        parent_id=None,
        sibling_group=None,
        depth=1,
        role="agent",
        session_name="agent-1",
        cwd=str(tmp_path),
    )

    store.upsert_agent(
        agent_id="agent-1",
        agent_handle="existing-handle",
        parent_id="session-node",
        sibling_group=None,
        depth=1,
        role="agent",
        session_name="existing",
        cwd=str(tmp_path),
    )

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id="session-node", cwd=str(tmp_path))
            ack = _dispatch(
                websocket,
                run_id="run-duplicate-handle",
                spec=_dispatch_spec(tmp_path),
                agent_id="agent-2",
                agent_handle="existing-handle",
            )

        assert ack == {
            "type": "dispatch_ack",
            "v": PROTOCOL_VERSION,
            "run_id": "run-duplicate-handle",
            "status": "rejected",
            "reason": "duplicate_agent_handle",
        }
    finally:
        _stop_daemon(server, thread, uds_path)


def test_dispatch_retasks_terminal_agent_by_handle(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-retask-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    agent_id = f"agent-{uuid.uuid4()}"
    handle = "scout-retask"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id="session-node", cwd=str(tmp_path))
            first_ack = _dispatch(
                websocket,
                run_id="run-retask-first",
                spec=_dispatch_spec(tmp_path, env={"FAKE_DAEMON_AGENT_SLEEP_MS": "20"}),
                agent_id=agent_id,
                agent_handle=handle,
                agent_type="scout",
                run_kind="named-read-only",
            )
            assert first_ack["status"] == "spawned"

        deadline = time.time() + 10
        while time.time() < deadline:
            first_run = store.get_run("run-retask-first")
            if first_run and first_run["status"] == "completed":
                break
            time.sleep(0.05)
        assert first_run is not None and first_run["status"] == "completed"

        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id="session-node", cwd=str(tmp_path))
            second_ack = _dispatch(
                websocket,
                run_id="run-retask-second",
                spec=_dispatch_spec(tmp_path),
                agent_handle=handle,
                agent_type="scout",
                run_kind="named-read-only",
            )

        assert second_ack == {
            "type": "dispatch_ack",
            "v": PROTOCOL_VERSION,
            "run_id": "run-retask-second",
            "status": "spawned",
            "reason": None,
        }

        second_run = store.get_run("run-retask-second")
        assert second_run is not None
        assert second_run["agent_id"] == agent_id
        agent = store.get_agent(agent_id)
        assert agent is not None
        assert agent["current_run_id"] == "run-retask-second"
        assert agent["agent_type"] == "scout"
        assert agent["run_kind"] == "named-read-only"
    finally:
        _stop_daemon(server, thread, uds_path)


def test_dispatch_rejects_retask_handle_from_other_root(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-retask-root-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    agent_id = f"agent-{uuid.uuid4()}"
    handle = "scout-owned-root"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id="owner-root", cwd=str(tmp_path))
            first_ack = _dispatch(
                websocket,
                run_id="run-retask-root-first",
                spec=_dispatch_spec(tmp_path, env={"FAKE_DAEMON_AGENT_SLEEP_MS": "20"}),
                agent_id=agent_id,
                agent_handle=handle,
                agent_type="scout",
                run_kind="named-read-only",
            )
            assert first_ack["status"] == "spawned"

        deadline = time.time() + 10
        while time.time() < deadline:
            first_run = store.get_run("run-retask-root-first")
            if first_run and first_run["status"] == "completed":
                break
            time.sleep(0.05)
        assert first_run is not None and first_run["status"] == "completed"

        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id="other-root", cwd=str(tmp_path))
            second_ack = _dispatch(
                websocket,
                run_id="run-retask-root-second",
                spec=_dispatch_spec(tmp_path),
                agent_handle=handle,
                agent_type="scout",
                run_kind="named-read-only",
            )

        assert second_ack == {
            "type": "dispatch_ack",
            "v": PROTOCOL_VERSION,
            "run_id": "run-retask-root-second",
            "status": "rejected",
            "reason": "duplicate_agent_handle",
        }
        assert store.get_run("run-retask-root-second") is None
        agent = store.get_agent(agent_id)
        assert agent is not None
        assert agent["current_run_id"] == "run-retask-root-first"
    finally:
        _stop_daemon(server, thread, uds_path)


def test_dispatch_rejects_active_retask_by_handle(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-retask-active-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    agent_id = f"agent-{uuid.uuid4()}"
    handle = "scout-active"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id="session-node", cwd=str(tmp_path))
            first_ack = _dispatch(
                websocket,
                run_id="run-retask-active-first",
                spec=_dispatch_spec(tmp_path, env={"FAKE_DAEMON_AGENT_SLEEP_MS": "1200"}),
                agent_id=agent_id,
                agent_handle=handle,
                agent_type="scout",
                run_kind="named-read-only",
            )
            second_ack = _dispatch(
                websocket,
                run_id="run-retask-active-second",
                spec=_dispatch_spec(tmp_path),
                agent_handle=handle,
                agent_type="scout",
                run_kind="named-read-only",
            )

        assert first_ack["status"] == "spawned"
        assert second_ack == {
            "type": "dispatch_ack",
            "v": PROTOCOL_VERSION,
            "run_id": "run-retask-active-second",
            "status": "rejected",
            "reason": "active_run_exists",
        }
        assert store.get_run("run-retask-active-second") is None
    finally:
        _stop_daemon(server, thread, uds_path)


def test_dispatch_rejects_agent_type_change_for_handle(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-retask-type-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    handle = "scout-type"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id="session-node", cwd=str(tmp_path))
            first_ack = _dispatch(
                websocket,
                run_id="run-retask-type-first",
                spec=_dispatch_spec(tmp_path, env={"FAKE_DAEMON_AGENT_SLEEP_MS": "20"}),
                agent_id=f"agent-{uuid.uuid4()}",
                agent_handle=handle,
                agent_type="scout",
                run_kind="named-read-only",
            )
            assert first_ack["status"] == "spawned"

        deadline = time.time() + 10
        while time.time() < deadline:
            first_run = store.get_run("run-retask-type-first")
            if first_run and first_run["status"] == "completed":
                break
            time.sleep(0.05)
        assert first_run is not None and first_run["status"] == "completed"

        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id="session-node", cwd=str(tmp_path))
            second_ack = _dispatch(
                websocket,
                run_id="run-retask-type-second",
                spec=_dispatch_spec(tmp_path),
                agent_handle=handle,
                agent_type="worker",
                run_kind="mutative",
            )

        assert second_ack == {
            "type": "dispatch_ack",
            "v": PROTOCOL_VERSION,
            "run_id": "run-retask-type-second",
            "status": "rejected",
            "reason": "agent_type_mismatch",
        }
        assert store.get_run("run-retask-type-second") is None
    finally:
        _stop_daemon(server, thread, uds_path)


def test_dispatch_rejected_when_depth_cap_exceeded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BASECAMP_AGENT_MAX_DEPTH", "2")

    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-depth-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    run_id = f"run-{uuid.uuid4()}"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            websocket.send(
                json.dumps(
                    {
                        "type": "register",
                        "v": PROTOCOL_VERSION,
                        "role": "agent",
                        "node_id": "depth-two-agent",
                        "parent_id": "parent",
                        "sibling_group": None,
                        "depth": 2,
                        "session_name": "depth-two-agent",
                        "cwd": str(tmp_path),
                    }
                )
            )
            websocket.recv()

            ack = _dispatch(websocket, run_id=run_id, spec=_dispatch_spec(tmp_path))

        assert ack == {
            "type": "dispatch_ack",
            "v": PROTOCOL_VERSION,
            "run_id": run_id,
            "status": "rejected",
            "reason": "depth_cap",
        }
        assert store.get_run(run_id) is None
    finally:
        _stop_daemon(server, thread, uds_path)
