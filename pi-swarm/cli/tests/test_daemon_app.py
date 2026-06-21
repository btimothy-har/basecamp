"""Tests for daemon HTTP and WebSocket skeleton behavior."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from pi_swarm.app import create_app
from pi_swarm.frames import PROTOCOL_VERSION
from pi_swarm.store import Store


def _build_app(tmp_path: Path):
    store = Store(db_path=tmp_path / "daemon.db")
    return create_app(store)


def _build_app_with_store(tmp_path: Path):
    store = Store(db_path=tmp_path / "daemon.db")
    return create_app(store), store


def test_health_endpoint(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "protocol": PROTOCOL_VERSION}


def test_ws_list_agents_returns_same_root_non_session_rows_and_awaitable_filters(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-a1",
        depth=1,
        role="agent",
        session_name="agent-one",
        cwd="/tmp/a1",
    )
    store.upsert_agent(
        agent_id="agent-2",
        parent_id="agent-1",
        sibling_group="sg-a2",
        depth=2,
        role="agent",
        session_name="agent-two",
        cwd="/tmp/a2",
    )
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group="sg-out",
        depth=0,
        role="session",
        session_name="outside-session",
        cwd="/tmp/out",
    )
    store.upsert_agent(
        agent_id="outside-agent",
        parent_id="outside-root",
        sibling_group="sg-out-a",
        depth=1,
        role="agent",
        session_name="outside-agent",
        cwd="/tmp/out-a",
    )

    store.create_run(
        run_id="run-1",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={"task": "a1"},
        report_token_hash="hash",
    )
    store.create_run(
        run_id="run-2",
        agent_id="agent-2",
        dispatcher_id="agent-1",
        spec={"task": "a2"},
        report_token_hash="hash",
    )
    store.set_run_result(
        run_id="run-2",
        status="completed",
        result="done",
        error=None,
    )

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as session_ws:
            session_ws.send_json(
                {
                    "type": "register",
                    "v": PROTOCOL_VERSION,
                    "role": "session",
                    "node_id": "root",
                    "parent_id": None,
                    "sibling_group": "sg-root",
                    "depth": 0,
                    "session_name": "root-session",
                    "cwd": "/tmp/root",
                }
            )
            session_ws.receive_json()

            with client.websocket_connect("/ws") as agent_ws:
                agent_ws.send_json(
                    {
                        "type": "register",
                        "v": PROTOCOL_VERSION,
                        "role": "agent",
                        "node_id": "agent-1",
                        "parent_id": "root",
                        "sibling_group": "sg-a1",
                        "depth": 1,
                        "session_name": "agent-one",
                        "cwd": "/tmp/a1",
                    }
                )
                agent_ws.receive_json()

                agent_ws.send_json(
                    {
                        "type": "list_agents",
                        "v": PROTOCOL_VERSION,
                        "request_id": "list-all",
                        "awaitable": False,
                    }
                )
                list_all = agent_ws.receive_json()
                assert list_all == {
                    "type": "list_agents_result",
                    "v": PROTOCOL_VERSION,
                    "request_id": "list-all",
                    "agents": [
                        {
                            "agent_id": "agent-1",
                            "agent_handle": "agent-1",
                            "parent_id": "root",
                            "role": "agent",
                            "session_name": "agent-one",
                            "depth": 1,
                            "status": "running",
                            "awaitable": False,
                        },
                        {
                            "agent_id": "agent-2",
                            "agent_handle": "agent-2",
                            "parent_id": "agent-1",
                            "role": "agent",
                            "session_name": "agent-two",
                            "depth": 2,
                            "status": "completed",
                            "awaitable": True,
                        },
                    ],
                }

                agent_ws.send_json(
                    {
                        "type": "list_agents",
                        "v": PROTOCOL_VERSION,
                        "request_id": "list-awaitable",
                        "awaitable": True,
                    }
                )
                list_awaitable = agent_ws.receive_json()
                assert list_awaitable == {
                    "type": "list_agents_result",
                    "v": PROTOCOL_VERSION,
                    "request_id": "list-awaitable",
                    "agents": [
                        {
                            "agent_id": "agent-2",
                            "agent_handle": "agent-2",
                            "parent_id": "agent-1",
                            "role": "agent",
                            "session_name": "agent-two",
                            "depth": 2,
                            "status": "completed",
                            "awaitable": True,
                        }
                    ],
                }


def test_ws_register_returns_registered(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "register",
                    "v": PROTOCOL_VERSION,
                    "role": "session",
                    "node_id": "node-1",
                    "parent_id": None,
                    "sibling_group": "sg-main",
                    "depth": 0,
                    "session_name": "test-session",
                    "cwd": "/tmp/project",
                }
            )
            reply = websocket.receive_json()

    assert reply == {
        "type": "registered",
        "v": PROTOCOL_VERSION,
        "node_id": "node-1",
        "protocol": PROTOCOL_VERSION,
    }


def test_ws_version_mismatch_returns_protocol_error(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "register",
                    "v": 99,
                    "role": "session",
                    "node_id": "node-1",
                    "parent_id": None,
                    "sibling_group": None,
                    "depth": 0,
                    "session_name": "test-session",
                    "cwd": "/tmp/project",
                }
            )
            reply = websocket.receive_json()

    assert reply["type"] == "error"
    assert reply["v"] == PROTOCOL_VERSION
    assert reply["code"] == "protocol_version"


def test_ws_unsupported_inbound_frame_returns_error(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "register",
                    "v": PROTOCOL_VERSION,
                    "role": "session",
                    "node_id": "node-1",
                    "parent_id": None,
                    "sibling_group": None,
                    "depth": 0,
                    "session_name": "test-session",
                    "cwd": "/tmp/project",
                }
            )
            websocket.receive_json()

            websocket.send_json(
                {
                    "type": "registered",
                    "v": PROTOCOL_VERSION,
                    "node_id": "node-1",
                    "protocol": PROTOCOL_VERSION,
                }
            )
            reply = websocket.receive_json()

    assert reply["type"] == "error"
    assert reply["v"] == PROTOCOL_VERSION
    assert reply["code"] == "unsupported_frame"
    assert "registered" in reply["message"]


def test_runs_summary_endpoint_returns_root_and_child_runs(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="child",
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="agent",
        session_name="child-agent",
        cwd="/tmp/child",
    )
    _insert_run(
        db_path=tmp_path / "daemon.db",
        run_id="run-root",
        agent_id="root",
        status="running",
        created_at="2026-01-01T00:00:00Z",
    )
    _insert_run(
        db_path=tmp_path / "daemon.db",
        run_id="run-child",
        agent_id="child",
        status="completed",
        created_at="2026-01-01T00:00:01Z",
    )

    with TestClient(app) as client:
        response = client.get("/runs/summary", params={"root_id": "root", "limit": 5})

    payload = response.json()

    assert response.status_code == 200
    assert payload["root_id"] == "root"
    assert payload["counts"] == {
        "pending": 0,
        "running": 1,
        "completed": 1,
        "failed": 0,
        "total": 2,
    }
    assert [run["run_id"] for run in payload["runs"]] == ["run-child", "run-root"]
    assert payload["runs"][0]["agent_id"] == "child"
    assert payload["session_active"] is False


def test_runs_summary_endpoint_marks_session_active_for_registered_root(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "register",
                    "v": PROTOCOL_VERSION,
                    "role": "session",
                    "node_id": "root",
                    "parent_id": None,
                    "sibling_group": "sg-root",
                    "depth": 0,
                    "session_name": "root-session",
                    "cwd": "/tmp/root",
                }
            )
            websocket.receive_json()

            response = client.get("/runs/summary", params={"root_id": "root"})

    assert response.status_code == 200
    assert response.json()["session_active"] is True


def test_runs_summary_endpoint_unknown_root_returns_empty_payload(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/runs/summary", params={"root_id": "missing-root"})

    assert response.status_code == 200
    assert response.json() == {
        "root_id": "missing-root",
        "session_active": False,
        "counts": {
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "total": 0,
        },
        "runs": [],
    }


def test_runs_summary_endpoint_respects_limit(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    _insert_run(
        db_path=tmp_path / "daemon.db",
        run_id="run-old",
        agent_id="root",
        status="completed",
        created_at="2026-01-01T00:00:00Z",
    )
    _insert_run(
        db_path=tmp_path / "daemon.db",
        run_id="run-mid",
        agent_id="root",
        status="completed",
        created_at="2026-01-02T00:00:00Z",
    )
    _insert_run(
        db_path=tmp_path / "daemon.db",
        run_id="run-new",
        agent_id="root",
        status="completed",
        created_at="2026-01-03T00:00:00Z",
    )

    with TestClient(app) as client:
        response = client.get("/runs/summary", params={"root_id": "root", "limit": 2})

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_active"] is False
    assert [run["run_id"] for run in payload["runs"]] == ["run-new", "run-mid"]

    with TestClient(app) as client:
        negative_limit = client.get("/runs/summary", params={"root_id": "root", "limit": -3})

    assert negative_limit.status_code == 200
    payload_negative = negative_limit.json()
    assert payload_negative["runs"] == []
    assert payload_negative["session_active"] is False
    assert payload_negative["counts"]["total"] == 3


def test_runs_summary_endpoint_omits_sensitive_and_full_fields(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    _insert_run(
        db_path=tmp_path / "daemon.db",
        run_id="run-sensitive",
        agent_id="root",
        status="failed",
        created_at="2026-01-01T00:00:00Z",
        spec_json='{"env": {"OPENAI_API_KEY": "secret"}}',
        report_token_hash="deadbeef" * 8,
        result="line one\nline two",
        error="x" * 200,
    )

    with TestClient(app) as client:
        response = client.get("/runs/summary", params={"root_id": "root"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["session_active"] is False
    assert len(payload["runs"]) == 1

    summary_run = payload["runs"][0]
    assert set(summary_run.keys()) == {
        "run_id",
        "agent_id",
        "agent_handle",
        "parent_id",
        "role",
        "session_name",
        "status",
        "result_preview",
        "error_preview",
        "exit_code",
        "created_at",
        "started_at",
        "ended_at",
    }
    assert "spec_json" not in summary_run
    assert "report_token_hash" not in summary_run
    assert "result" not in summary_run
    assert "error" not in summary_run
    assert summary_run["result_preview"] == "line one line two"
    assert summary_run["error_preview"].endswith("…")
    assert len(summary_run["error_preview"]) == 160


def _insert_run(
    *,
    db_path: Path,
    run_id: str,
    agent_id: str,
    status: str,
    created_at: str,
    spec_json: str = "{}",
    report_token_hash: str | None = None,
    result: str | None = None,
    error: str | None = None,
    exit_code: int | None = None,
) -> None:
    started_at = created_at
    ended_at = created_at if status in {"completed", "failed"} else None

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO runs (
                id,
                agent_id,
                status,
                spec_json,
                report_token_hash,
                result,
                error,
                exit_code,
                created_at,
                started_at,
                ended_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                agent_id,
                status,
                spec_json,
                report_token_hash,
                result,
                error,
                exit_code,
                created_at,
                started_at,
                ended_at,
            ),
        )
