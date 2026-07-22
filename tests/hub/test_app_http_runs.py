"""Daemon app HTTP tests for the compact run summary."""

from __future__ import annotations

from pathlib import Path

from app_helpers import _build_app, _build_app_with_store
from fastapi.testclient import TestClient
from store_helpers import _insert_run, _write_task_log

from basecamp.hub.store import Store


def _root(store: Store) -> None:
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="agent",
        session_name="root-session",
        cwd="/tmp/root",
    )


def _child(store: Store, agent_id: str) -> None:
    store.upsert_agent(
        agent_id=agent_id,
        parent_id="root",
        sibling_group=f"sg-{agent_id}",
        depth=1,
        role="worker",
        session_name=f"{agent_id}-session",
        cwd=f"/tmp/{agent_id}",
        agent_type="worker",
    )


def test_runs_summary_endpoint_returns_only_widget_fields(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)
    _root(store)
    _child(store, "child")
    _insert_run(
        db_path=tmp_path / "daemon.db",
        run_id="run-child",
        agent_id="child",
        status="running",
        created_at="2026-01-01T00:00:00Z",
        spec_json='{"env": {"OPENAI_API_KEY": "secret"}}',
        report_token_hash="secret-token-hash",
        result="private result",
        error="private error",
    )
    _write_task_log(
        store.task_dir,
        "child",
        [
            {
                "goal": "Ship compact summary",
                "active": True,
                "tasks": [{"label": "Current task", "description": "private detail", "status": "active"}],
            }
        ],
    )

    with TestClient(app) as client:
        response = client.get("/runs/summary", params={"root_id": "root", "limit": 5})

    assert response.status_code == 200
    assert response.json() == {
        "agents": [
            {
                "agent_handle": "child",
                "agent_type": "worker",
                "session_name": "child-session",
                "status": "running",
                "created_at": "2026-01-01T00:00:00Z",
                "started_at": "2026-01-01T00:00:00Z",
                "task": {"goal": "Ship compact summary", "current_task": {"label": "Current task"}},
            }
        ]
    }


def test_runs_summary_endpoint_unknown_root_returns_empty_agents(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/runs/summary", params={"root_id": "missing-root"})

    assert response.status_code == 200
    assert response.json() == {"agents": []}


def test_runs_summary_endpoint_respects_limit(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)
    _root(store)
    for agent_id, created_at in [
        ("agent-old", "2026-01-01T00:00:00Z"),
        ("agent-mid", "2026-01-02T00:00:00Z"),
        ("agent-new", "2026-01-03T00:00:00Z"),
    ]:
        _child(store, agent_id)
        _insert_run(
            db_path=tmp_path / "daemon.db",
            run_id=f"run-{agent_id}",
            agent_id=agent_id,
            status="completed",
            created_at=created_at,
        )

    with TestClient(app) as client:
        limited = client.get("/runs/summary", params={"root_id": "root", "limit": 2})
        negative = client.get("/runs/summary", params={"root_id": "root", "limit": -3})

    assert limited.status_code == 200
    assert [agent["agent_handle"] for agent in limited.json()["agents"]] == ["agent-new", "agent-mid"]
    assert negative.status_code == 200
    assert negative.json() == {"agents": []}


def test_runs_messages_endpoint_is_removed(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get(
            "/runs/messages",
            params={"root_id": "root", "agent_handle": "agent-1"},
        )

    assert response.status_code == 404
