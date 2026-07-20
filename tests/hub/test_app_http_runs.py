"""Daemon app HTTP /runs summary and messages projection tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app_helpers import _build_app, _build_app_with_store
from fastapi.testclient import TestClient
from store_helpers import _insert_run, _write_task_log

from basecamp.hub.frames import PROTOCOL_VERSION


def test_runs_summary_endpoint_returns_child_agents(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="agent",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="child",
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="worker",
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
    assert [agent["agent_handle"] for agent in payload["agents"]] == ["child"]
    assert payload["agents"][0]["status"] == "completed"
    assert payload["session_active"] is False


def test_runs_summary_endpoint_marks_session_active_for_registered_root(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="agent",
        session_name="root-session",
        cwd="/tmp/root",
    )

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "register",
                    "v": PROTOCOL_VERSION,
                    "role": "agent",
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
        "agents": [],
    }


def test_runs_summary_endpoint_respects_limit(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="agent",
        session_name="root-session",
        cwd="/tmp/root",
    )
    for agent_id, created_at in [
        ("agent-old", "2026-01-01T00:00:00Z"),
        ("agent-mid", "2026-01-02T00:00:00Z"),
        ("agent-new", "2026-01-03T00:00:00Z"),
    ]:
        store.upsert_agent(
            agent_id=agent_id,
            parent_id="root",
            sibling_group=f"sg-{agent_id}",
            depth=1,
            role="worker",
            session_name=agent_id,
            cwd=f"/tmp/{agent_id}",
        )
        _insert_run(
            db_path=tmp_path / "daemon.db",
            run_id=f"run-{agent_id}",
            agent_id=agent_id,
            status="completed",
            created_at=created_at,
        )

    with TestClient(app) as client:
        response = client.get("/runs/summary", params={"root_id": "root", "limit": 2})

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_active"] is False
    assert [agent["agent_handle"] for agent in payload["agents"]] == ["agent-new", "agent-mid"]

    with TestClient(app) as client:
        negative_limit = client.get("/runs/summary", params={"root_id": "root", "limit": -3})

    assert negative_limit.status_code == 200
    payload_negative = negative_limit.json()
    assert payload_negative["agents"] == []
    assert payload_negative["session_active"] is False
    assert payload_negative["counts"]["total"] == 3


def test_runs_summary_endpoint_omits_sensitive_and_full_fields(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="agent",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="child",
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="worker",
        session_name="child-agent",
        cwd="/tmp/child",
    )
    _insert_run(
        db_path=tmp_path / "daemon.db",
        run_id="run-sensitive",
        agent_id="child",
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
    assert len(payload["agents"]) == 1

    summary_agent = payload["agents"][0]
    assert set(summary_agent.keys()) == {
        "agent_handle",
        "agent_id_short",
        "agent_type",
        "model",
        "role",
        "session_name",
        "status",
        "result_preview",
        "error_preview",
        "exit_code",
        "created_at",
        "started_at",
        "ended_at",
        "task",
        "recent_activity",
        "skills",
    }
    assert "run_id" not in summary_agent
    assert "agent_id" not in summary_agent
    assert "spec_json" not in summary_agent
    assert "report_token_hash" not in summary_agent
    assert "result" not in summary_agent
    assert "error" not in summary_agent
    assert summary_agent["agent_id_short"] == "child"
    assert summary_agent["model"] == "default"
    assert summary_agent["result_preview"] == "line one line two"
    assert summary_agent["error_preview"].endswith("…")
    assert len(summary_agent["error_preview"]) == 160
    assert summary_agent["task"] is None
    assert summary_agent["recent_activity"] == []
    assert summary_agent["skills"] == []


def test_runs_messages_endpoint_projects_selected_agent_messages(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="agent",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="worker",
        session_name="child-agent",
        cwd="/tmp/child",
    )
    store.create_run(
        run_id="run-1",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={"prompt": "do not expose"},
        report_token_hash="secret-token-hash",
    )
    store.append_run_event(
        run_id="run-1",
        kind="assistant_output",
        payload={
            "label": "assistant",
            "snippet": "short",
            "text": "full\nassistant message",
            "toolCallId": "private",
            "raw": {"secret": "ignored"},
        },
    )

    with TestClient(app) as client:
        response = client.get(
            "/runs/messages",
            params={"root_id": "root", "agent_handle": "agent-1", "limit": 3},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload == {
        "root_id": "root",
        "agent_handle": "agent-1",
        "messages": [
            {
                "kind": "assistant_output",
                "seq": 1,
                "timestamp": payload["messages"][0]["timestamp"],
                "label": "assistant",
                "text": "full\nassistant message",
            }
        ],
    }
    assert set(payload["messages"][0]) == {"kind", "seq", "timestamp", "label", "text"}


def test_runs_summary_endpoint_projects_task_log_and_activity(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="agent",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="worker",
        session_name="child-agent",
        cwd="/tmp/child",
    )
    store.create_run(
        run_id="run-1",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={"env": {"SECRET": "nope"}},
        report_token_hash="secret-token-hash",
    )
    store.append_run_event(
        run_id="run-1",
        kind="tool_execution_end",
        payload={
            "toolName": "bash",
            "turnIndex": 4,
            "args": {"command": "cat secret"},
            "output": "private output",
            "payload": {"raw": "private"},
            "toolCallId": "call-secret",
        },
    )
    with sqlite3.connect(tmp_path / "daemon.db") as connection:
        connection.execute(
            "UPDATE run_events SET ts = ? WHERE run_id = ? AND seq = ?",
            ("2026-01-01T00:00:00Z", "run-1", 1),
        )
    _write_task_log(
        store.task_dir,
        "agent-1",
        [
            {
                "goal": "Verify summary",
                "active": True,
                "tasks": [
                    {"label": "Done", "description": "d", "status": "completed"},
                    {"label": 123, "description": "bad", "status": "completed"},
                    {"label": "Current", "description": "desc", "status": "active"},
                ],
            }
        ],
    )

    with TestClient(app) as client:
        response = client.get("/runs/summary", params={"root_id": "root"})

    payload = response.json()
    assert response.status_code == 200
    assert len(payload["agents"]) == 1
    summary_agent = payload["agents"][0]
    assert "agent_id" not in summary_agent
    assert "run_id" not in summary_agent
    assert "spec_json" not in summary_agent
    assert "report_token_hash" not in summary_agent
    assert summary_agent["agent_id_short"] == "agent1"
    assert summary_agent["model"] == "default"
    assert summary_agent["task"] == {
        "goal": "Verify summary",
        "progress": {"completed": 1, "deleted": 0, "total": 2},
        "task_plan": [
            {"index": 0, "label": "Done", "status": "completed"},
            {"index": 2, "label": "Current", "status": "active"},
        ],
        "current_task": {
            "index": 2,
            "label": "Current",
            "status": "active",
            "description": "desc",
        },
    }
    assert summary_agent["recent_activity"] == [
        {
            "kind": "tool_execution_end",
            "seq": 1,
            "timestamp": "2026-01-01T00:00:00Z",
            "toolName": "bash",
            "turnIndex": 4,
        }
    ]
    assert all(key not in summary_agent["recent_activity"][0] for key in ["args", "output", "payload", "toolCallId"])
