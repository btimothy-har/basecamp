"""Private UDS dashboard projection route tests."""

from __future__ import annotations

from pathlib import Path

from app_helpers import _build_app_with_store, _register_ws
from fastapi.testclient import TestClient

from basecamp.hub.app import create_app
from basecamp.hub.dashboard.access import DashboardAccess
from basecamp.hub.store import Store


def test_private_dashboard_bootstrap_route_requires_available_listener(tmp_path: Path) -> None:
    access = DashboardAccess(token_factory=lambda: "n" * 43)
    app = create_app(
        Store(db_path=tmp_path / "daemon.db", task_dir=tmp_path / "tasks"),
        dashboard_access=access,
    )

    with TestClient(app) as client:
        unavailable = client.post("/dashboard/bootstrap")
        access.set_available("http://127.0.0.1:47658")
        available = client.post("/dashboard/bootstrap")
        wrong_method = client.get("/dashboard/bootstrap")

    assert unavailable.status_code == 503
    assert "has not started" in unavailable.json()["detail"]
    assert available.status_code == 200
    assert available.headers["cache-control"] == "no-store"
    assert available.json() == {"url": f"http://127.0.0.1:47658/bootstrap/{'n' * 43}"}
    assert wrong_method.status_code == 405


def test_dashboard_snapshot_route_merges_live_registry_state(tmp_path: Path) -> None:
    app, _store = _build_app_with_store(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            _register_ws(
                websocket,
                node_id="root-private",
                role="agent",
                parent_id=None,
                sibling_group=None,
                agent_handle="root-handle",
            )
            response = client.get("/dashboard/snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["window_hours"] == 72
    assert [root["root_handle"] for root in payload["roots"]] == ["root-handle"]
    assert payload["roots"][0]["live"] is True
    assert "id" not in payload["roots"][0]


def test_dashboard_messages_route_uses_public_handles(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)
    store.upsert_agent(
        agent_id="root-private",
        agent_handle="root-handle",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="agent",
        session_name="root",
        cwd="/private/root",
    )
    store.upsert_agent(
        agent_id="agent-private",
        agent_handle="agent-handle",
        parent_id="root-private",
        sibling_group="root-private",
        depth=1,
        role="worker",
        session_name="agent",
        cwd="/private/agent",
    )
    store.create_run(
        run_id="run-private",
        agent_id="agent-private",
        dispatcher_id="root-private",
        spec={},
    )
    store.append_run_event(
        run_id="run-private",
        kind="assistant_output",
        payload={"text": "Safe visible output"},
    )

    with TestClient(app) as client:
        response = client.get(
            "/dashboard/messages",
            params={"root_handle": "root-handle", "agent_handle": "agent-handle"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["root_handle"] == "root-handle"
    assert payload["agent_handle"] == "agent-handle"
    assert len(payload["messages"]) == 1
    assert payload["messages"][0]["kind"] == "assistant_output"
    assert payload["messages"][0]["seq"] == 1
    assert payload["messages"][0]["timestamp"] is not None
    assert payload["messages"][0]["label"] is None
    assert payload["messages"][0]["text"] == "Safe visible output"
    assert payload["messages"][0]["truncated"] is False

    with TestClient(app) as client:
        invalid = client.get(
            "/dashboard/messages",
            params={"root_handle": "root/invalid", "agent_handle": "agent-handle"},
        )
    assert invalid.status_code == 422
