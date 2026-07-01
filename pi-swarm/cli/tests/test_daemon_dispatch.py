"""Daemon dispatch/wait/result round-trip tests."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest
import uvicorn
from pi_swarm.app import create_app
from pi_swarm.frames import PROTOCOL_VERSION, DispatchFrame, DispatchSpec
from pi_swarm.process import build_runner_argv, reap_agent_process
from pi_swarm.registry import Registry
from pi_swarm.run_result import load_run_result, run_result_path
from pi_swarm.server import UdsServer
from pi_swarm.service import DispatchRejection, PreparedDispatch, prepare_dispatch
from pi_swarm.store import Store
from websockets.sync.client import unix_connect


class _ThreadedServer(UdsServer):
    def install_signal_handlers(self) -> None:  # noqa: D401
        """Disable signal handlers when running under a background thread."""


class _FakeProcess:
    async def wait(self) -> int:
        return 7


class _StoreFailureError(Exception):
    pass


class _FailingStore:
    def set_run_exit_code(self, *, run_id: str, exit_code: int) -> None:
        assert run_id == "run-failing-store"
        assert exit_code == 7
        raise _StoreFailureError

    def set_run_result_if_unset(self, **_kwargs: object) -> bool:
        raise AssertionError


@pytest.fixture(autouse=True)
def _isolate_run_result_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


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
                "v": PROTOCOL_VERSION,
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


def test_build_runner_argv_injects_fork_before_task() -> None:
    spec = DispatchSpec(
        argv=["pi", "--mode", "json", "-p"],
        env={},
        cwd="/tmp/project",
        resume_path=None,
        task="answer this question",
    )

    argv = build_runner_argv(
        result_path=Path("/tmp/result.json"),
        spec=spec,
        fork_source_path="/tmp/source.jsonl",
    )

    assert argv == [
        sys.executable,
        "-m",
        "pi_swarm.runner",
        "--result-path",
        "/tmp/result.json",
        "--",
        "pi",
        "--mode",
        "json",
        "-p",
        "--fork",
        "/tmp/source.jsonl",
        "answer this question",
    ]


def test_build_runner_argv_omits_fork_when_unset() -> None:
    spec = DispatchSpec(
        argv=["pi", "--mode", "json", "-p"],
        env={},
        cwd="/tmp/project",
        resume_path=None,
        task="answer this question",
    )

    argv = build_runner_argv(
        result_path=Path("/tmp/result.json"),
        spec=spec,
        fork_source_path=None,
    )

    assert "--fork" not in argv
    assert argv[-1] == "answer this question"


@pytest.mark.asyncio
async def test_prepare_dispatch_resolves_fork_from_target_handle(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    home = tmp_path / "home"
    session_file = _write_agent_session_file(home, "target-agent")
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd=str(tmp_path),
    )
    store.upsert_agent(
        agent_id="target-agent",
        agent_handle="target-handle",
        parent_id="root",
        sibling_group="sg-target",
        depth=1,
        role="agent",
        session_name="target-agent",
        cwd=str(tmp_path),
    )
    frame = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="run-answerer",
        agent_id="answerer-agent",
        spec=DispatchSpec(
            argv=["pi", "--mode", "json", "-p"],
            env={"HOME": str(home)},
            cwd=str(tmp_path),
            resume_path=None,
            fork_from="target-handle",
            task="question?",
        ),
    )

    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id="root",
        store=store,
    )

    assert isinstance(dispatch, PreparedDispatch)
    assert dispatch.fork_source_path == str(session_file.resolve())
    agent = store.get_agent("answerer-agent")
    assert agent is not None
    assert agent["sibling_group"] == "root"


@pytest.mark.asyncio
async def test_prepare_dispatch_rejects_unauthorized_fork_from_target(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    home = tmp_path / "home"
    _write_agent_session_file(home, "outside-agent")
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root-session",
        cwd=str(tmp_path),
    )
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="outside-root-session",
        cwd=str(tmp_path),
    )
    store.upsert_agent(
        agent_id="outside-agent",
        agent_handle="outside-handle",
        parent_id="outside-root",
        sibling_group="outside-root",
        depth=1,
        role="agent",
        session_name="outside-agent",
        cwd=str(tmp_path),
    )
    frame = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="run-answerer",
        agent_id="answerer-agent",
        spec=DispatchSpec(
            argv=["pi", "--mode", "json", "-p"],
            env={"HOME": str(home)},
            cwd=str(tmp_path),
            resume_path=None,
            fork_from="outside-handle",
            task="question?",
        ),
    )

    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id="root",
        store=store,
    )

    assert dispatch == DispatchRejection(reason="fork_target_unknown")
    assert store.get_run("run-answerer") is None


@pytest.mark.asyncio
async def test_prepare_dispatch_persists_new_agent_sibling_group(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root-session",
        cwd=str(tmp_path),
    )
    frame = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="run-child",
        agent_id="child-agent",
        spec=DispatchSpec(
            argv=["pi", "--mode", "json", "-p"],
            env={},
            cwd=str(tmp_path),
            resume_path=None,
            task="do work",
        ),
    )

    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id="root",
        store=store,
    )

    assert isinstance(dispatch, PreparedDispatch)
    agent = store.get_agent("child-agent")
    assert agent is not None
    assert agent["sibling_group"] == "root"


@pytest.mark.asyncio
async def test_prepare_dispatch_rejects_unknown_fork_from_target(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    home = tmp_path / "home"
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd=str(tmp_path),
    )
    frame = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="run-answerer",
        agent_id="answerer-agent",
        spec=DispatchSpec(
            argv=["pi", "--mode", "json", "-p"],
            env={"HOME": str(home)},
            cwd=str(tmp_path),
            resume_path=None,
            fork_from="missing-target",
            task="question?",
        ),
    )

    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id="root",
        store=store,
    )

    assert dispatch == DispatchRejection(reason="fork_target_unknown")
    assert store.get_run("run-answerer") is None


@pytest.mark.asyncio
async def test_reap_agent_process_removes_registry_process_when_store_update_fails() -> None:
    run_id = "run-failing-store"
    registry = Registry()
    process = _FakeProcess()
    registry.set_process(run_id, process)

    async def on_finalize(_run_id: str) -> None:
        raise AssertionError

    with pytest.raises(_StoreFailureError):
        await reap_agent_process(
            run_id=run_id,
            process=process,
            registry=registry,
            store=_FailingStore(),
            on_finalize=on_finalize,
        )

    assert registry.pop_process(run_id) is None


@pytest.mark.asyncio
async def test_reap_agent_process_does_not_overwrite_reported_result(tmp_path: Path) -> None:
    run_id = "run-already-reported"
    agent_id = "agent-already-reported"
    registry = Registry()
    process = _FakeProcess()
    store = Store(db_path=tmp_path / "daemon.db")
    finalized: list[str] = []

    store.upsert_agent(
        agent_id=agent_id,
        agent_handle=None,
        parent_id=None,
        sibling_group=None,
        depth=1,
        role="agent",
        session_name=agent_id,
        cwd=str(tmp_path),
    )
    store.create_run(
        run_id=run_id,
        agent_id=agent_id,
        dispatcher_id="session-node",
        spec={},
    )
    store.set_run_result_if_unset(
        run_id=run_id,
        status="completed",
        result="runner-final-result",
        error=None,
    )
    registry.set_process(run_id, process)

    async def on_finalize(finalized_run_id: str) -> None:
        finalized.append(finalized_run_id)

    await reap_agent_process(
        run_id=run_id,
        process=process,
        registry=registry,
        store=store,
        on_finalize=on_finalize,
    )

    run = store.get_run(run_id)
    assert run is not None
    assert run["status"] == "completed"
    assert run["result"] == "runner-final-result"
    assert run["exit_code"] == 7
    assert finalized == []
    assert registry.pop_process(run_id) is None


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
