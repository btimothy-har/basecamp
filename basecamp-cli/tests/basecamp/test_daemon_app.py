"""Tests for daemon HTTP and WebSocket skeleton behavior."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from basecamp.daemon.app import create_app
from basecamp.daemon.store import Store
from fastapi.testclient import TestClient


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
    assert response.json() == {"status": "ok", "protocol": 2}


def test_ws_register_returns_registered(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "register",
                    "v": 2,
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
        "v": 2,
        "node_id": "node-1",
        "protocol": 2,
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
    assert reply["v"] == 2
    assert reply["code"] == "protocol_version"


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


def test_runs_summary_endpoint_unknown_root_returns_empty_payload(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/runs/summary", params={"root_id": "missing-root"})

    assert response.status_code == 200
    assert response.json() == {
        "root_id": "missing-root",
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
    assert [run["run_id"] for run in payload["runs"]] == ["run-new", "run-mid"]

    with TestClient(app) as client:
        negative_limit = client.get("/runs/summary", params={"root_id": "root", "limit": -3})

    assert negative_limit.status_code == 200
    payload_negative = negative_limit.json()
    assert payload_negative["runs"] == []
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
    assert len(payload["runs"]) == 1

    summary_run = payload["runs"][0]
    assert set(summary_run.keys()) == {
        "run_id",
        "agent_id",
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

