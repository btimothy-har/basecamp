"""Daemon dispatch/wait/result round-trip tests."""

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
                "v": 4,
                "role": "session",
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
                "v": 4,
                "role": "agent",
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
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "dispatch",
        "v": 4,
        "run_id": run_id,
        "spec": spec,
    }
    if agent_id is not None:
        payload["agent_id"] = agent_id

    websocket.send(json.dumps(payload))
    return json.loads(websocket.recv())


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
                "v": 4,
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
                "v": 4,
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

    try:
        with unix_connect(str(uds_path), uri="ws://localhost/ws") as websocket:
            _register_session(websocket, node_id=session_node, cwd=str(tmp_path))
            ack = _dispatch(websocket, run_id=run_id, spec=_dispatch_spec(tmp_path), agent_id=provided_agent_id)
            assert ack == {
                "type": "dispatch_ack",
                "v": 4,
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

        agent = store.get_agent(provided_agent_id)
        assert agent is not None
        assert agent["id"] == provided_agent_id
        assert agent["parent_id"] == session_node
    finally:
        _stop_daemon(server, thread, uds_path)


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
            "v": 4,
            "run_id": second_run_id,
            "status": "rejected",
            "reason": "active_run_exists",
        }
        assert store.get_run(second_run_id) is None
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
                "v": 4,
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
                        "v": 4,
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
                        "v": 4,
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
                        "v": 4,
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
        assert "code 9" in (item["error"] or "")

        run = store.get_run(run_id)
        assert run is not None
        assert run["status"] == "failed"
        assert "code 9" in (run["error"] or "")
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
                        "v": 4,
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
                        "v": 4,
                        "agent_ids": [agent_id],
                        "mode": "all",
                        "timeout_s": 10,
                    }
                )
            )
            wait_result = json.loads(requester.recv())

        elapsed = time.time() - start
        assert elapsed < 2.0
        assert wait_result["results"] == [
            {"agent_id": agent_id, "status": "unknown", "result": None, "error": None}
        ]
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
                        "v": 4,
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
                        "v": 4,
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
            "v": 4,
            "run_id": run_id,
            "status": "rejected",
            "reason": "depth_cap",
        }
        assert store.get_run(run_id) is None
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
                "v": 4,
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
                "v": 4,
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
                        "v": 4,
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
                        "v": 4,
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
                        "v": 4,
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
                        "v": 4,
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
        assert "agent process exited" in str(run["error"])
        assert run["result"] != "attacker-result"

        events = store.get_run_events(run_id)
        assert all(event["kind"] != "tool_execution_end" for event in events)
    finally:
        _stop_daemon(server, thread, uds_path)
