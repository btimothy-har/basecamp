"""Daemon dispatch/spawn/result round-trip tests."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import uvicorn
from basecamp.daemon.app import create_app
from basecamp.daemon.server import UdsServer
from basecamp.daemon.store import Store
from websockets.sync.client import unix_connect


class _ThreadedServer(UdsServer):
    def install_signal_handlers(self) -> None:  # noqa: D401
        """Disable signal handlers when running under a background thread."""


def _start_daemon(store: Store, uds_path: Path) -> tuple[UdsServer, threading.Thread]:
    app = create_app(store, daemon_uds=str(uds_path))
    config = uvicorn.Config(app=app, uds=str(uds_path), log_level="error")
    server = _ThreadedServer(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while time.time() < deadline and not uds_path.exists():
        time.sleep(0.05)

    return server, thread


def _stop_daemon(server: UdsServer, thread: threading.Thread, uds_path: Path) -> None:
    server.should_exit = True
    thread.join(timeout=5)
    if uds_path.exists():
        uds_path.unlink()


def _dispatch_spec(tmp_path: Path) -> dict[str, object]:
    helper_script = Path(__file__).with_name("fake_daemon_agent.py")
    return {
        "argv": [sys.executable, str(helper_script)],
        "env": {},
        "cwd": str(tmp_path),
        "resume_path": None,
        "task": "deterministic fake task",
    }


def test_daemon_dispatch_spawn_and_result_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-dispatch-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=db_path)
    server, thread = _start_daemon(store, uds_path)

    run_id = f"run-{uuid.uuid4()}"
    session_node = "session-node"

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            websocket.send(
                json.dumps(
                    {
                        "type": "register",
                        "v": 1,
                        "role": "session",
                        "node_id": session_node,
                        "parent_id": None,
                        "sibling_group": None,
                        "depth": 0,
                        "session_name": "session-node",
                        "cwd": str(tmp_path),
                    }
                )
            )
            registered = json.loads(websocket.recv())
            assert registered["type"] == "registered"

            websocket.send(
                json.dumps(
                    {
                        "type": "dispatch",
                        "v": 1,
                        "run_id": run_id,
                        "spec": _dispatch_spec(tmp_path),
                    }
                )
            )
            ack = json.loads(websocket.recv())
            assert ack == {
                "type": "dispatch_ack",
                "v": 1,
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

        events = store.get_run_events(run_id)
        assert len(events) >= 1

        agent_id = run["agent_id"]
        agent = store.get_agent(agent_id)
        assert agent is not None
        assert agent["depth"] == 1
        assert agent["parent_id"] == session_node
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
                        "v": 1,
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

            websocket.send(
                json.dumps(
                    {
                        "type": "dispatch",
                        "v": 1,
                        "run_id": run_id,
                        "spec": _dispatch_spec(tmp_path),
                    }
                )
            )
            ack = json.loads(websocket.recv())

        assert ack == {
            "type": "dispatch_ack",
            "v": 1,
            "run_id": run_id,
            "status": "rejected",
            "reason": "depth_cap",
        }
        assert store.get_run(run_id) is None
    finally:
        _stop_daemon(server, thread, uds_path)
