"""Shared daemon-dispatch test harness: fakes, daemon runner, and WS helpers."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import uvicorn

from basecamp.hub.app import create_app
from basecamp.hub.frames import PROTOCOL_VERSION
from basecamp.hub.registry import Registry
from basecamp.hub.server import UdsServer
from basecamp.hub.store import Store


class _ThreadedServer(UdsServer):
    def install_signal_handlers(self) -> None:  # noqa: D401
        """Disable signal handlers when running under a background thread."""


class _FakeProcess:
    async def wait(self) -> int:
        return 7


class _FakePidProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid


class _StoreFailureError(Exception):
    pass


class _FailingStore:
    def set_run_exit_code(self, *, run_id: str, exit_code: int) -> None:
        assert run_id == "run-failing-store"
        assert exit_code == 7
        raise _StoreFailureError

    def set_run_result_if_unset(self, **_kwargs: object) -> bool:
        raise AssertionError


def _upsert_test_agent(
    store: Store,
    *,
    agent_id: str,
    parent_id: str | None,
    depth: int,
    agent_handle: str | None = None,
    role: str = "agent",
) -> None:
    store.upsert_agent(
        agent_id=agent_id,
        agent_handle=agent_handle,
        parent_id=parent_id,
        sibling_group=parent_id,
        depth=depth,
        role=role,
        session_name=agent_id,
        cwd=f"/tmp/{agent_id}",
    )


def _create_live_run(
    store: Store,
    registry: Registry,
    *,
    agent_id: str,
    run_id: str,
    dispatcher_id: str,
    pid: int,
) -> None:
    store.create_run(
        run_id=run_id,
        agent_id=agent_id,
        dispatcher_id=dispatcher_id,
        spec={"task": run_id},
        report_token_hash="hash",
    )
    registry.set_process(run_id, _FakePidProcess(pid))


def _start_daemon(store: Store, uds_path: Path) -> tuple[UdsServer, threading.Thread]:
    app = create_app(store, daemon_uds=str(uds_path))
    config = uvicorn.Config(app=app, uds=str(uds_path), log_level="error")
    server = _ThreadedServer(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while time.time() < deadline and not uds_path.exists():
        time.sleep(0.05)

    assert uds_path.exists(), f"daemon failed to start: socket not created at {uds_path}"
    return server, thread


def _stop_daemon(server: UdsServer, thread: threading.Thread, uds_path: Path) -> None:
    server.should_exit = True
    thread.join(timeout=5)
    if uds_path.exists():
        uds_path.unlink()


def _dispatch_spec(
    tmp_path: Path,
    *,
    env: dict[str, str] | None = None,
    argv: list[str] | None = None,
) -> dict[str, object]:
    helper_script = Path(__file__).with_name("fake_daemon_agent.py")
    return {
        "argv": argv or [sys.executable, str(helper_script)],
        "env": env or {},
        "cwd": str(tmp_path),
        "resume_path": None,
        "task": "deterministic fake task",
    }


def _register_session(websocket, *, node_id: str, cwd: str) -> None:
    websocket.send(
        json.dumps(
            {
                "type": "register",
                "v": PROTOCOL_VERSION,
                "role": "agent",
                "node_id": node_id,
                "parent_id": None,
                "sibling_group": None,
                "depth": 0,
                "session_name": node_id,
                "cwd": cwd,
            }
        )
    )
    registered = json.loads(websocket.recv())
    assert registered["type"] == "registered"


def _register_agent(websocket, *, node_id: str, cwd: str) -> None:
    websocket.send(
        json.dumps(
            {
                "type": "register",
                "v": PROTOCOL_VERSION,
                "role": "worker",
                "node_id": node_id,
                "parent_id": None,
                "sibling_group": None,
                "depth": 1,
                "session_name": node_id,
                "cwd": cwd,
            }
        )
    )
    registered = json.loads(websocket.recv())
    assert registered["type"] == "registered"


def _dispatch(
    websocket,
    *,
    run_id: str,
    spec: dict[str, object],
    agent_id: str | None = None,
    agent_handle: str | None = None,
    agent_type: str | None = None,
    run_kind: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "dispatch",
        "v": PROTOCOL_VERSION,
        "run_id": run_id,
        "spec": spec,
    }
    if agent_id is not None:
        payload["agent_id"] = agent_id
    if agent_handle is not None:
        payload["agent_handle"] = agent_handle
    if agent_type is not None:
        payload["agent_type"] = agent_type
    if run_kind is not None:
        payload["run_kind"] = run_kind

    websocket.send(json.dumps(payload))
    return json.loads(websocket.recv())


def _write_agent_session_file(home: Path, agent_id: str) -> Path:
    session_dir = home / ".pi" / "basecamp" / "swarm" / "agents" / agent_id / "session"
    session_dir.mkdir(parents=True)
    session_file = session_dir / f"2026-01-01T00-00-00_{agent_id}.jsonl"
    session_file.write_text("{}\n", encoding="utf-8")
    return session_file
