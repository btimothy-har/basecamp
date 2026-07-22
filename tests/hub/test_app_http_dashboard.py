"""Private UDS dashboard projection route tests."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from typing import cast

import pytest
from app_helpers import _build_app_with_store, _register_ws
from fastapi.testclient import TestClient

from basecamp.hub.app import create_app
from basecamp.hub.dashboard.access import DashboardAccess
from basecamp.hub.http_routes import _SnapshotBusyError, _SnapshotSingleFlight
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
            response = client.get(
                "/dashboard/snapshot",
                params={"recent_root_limit": 10, "selected_root_handle": "root-handle"},
            )
            invalid_handle = client.get(
                "/dashboard/snapshot",
                params={"selected_root_handle": "root/invalid"},
            )
            invalid_limit = client.get(
                "/dashboard/snapshot",
                params={"recent_root_limit": 51},
            )

    assert response.status_code == 200
    assert invalid_handle.status_code == 422
    assert invalid_limit.status_code == 422
    payload = response.json()
    assert payload["window_hours"] == 24
    assert payload["recent_root_limit"] == 10
    assert [root["root_handle"] for root in payload["roots"]] == ["root-handle"]
    assert payload["roots"][0]["live"] is True
    assert "id" not in payload["roots"][0]


@pytest.mark.asyncio
async def test_snapshot_single_flight_survives_request_cancellation() -> None:
    flight = _SnapshotSingleFlight()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    calls = 0

    def project() -> dict[str, object]:
        nonlocal calls
        calls += 1
        started.set()
        try:
            assert release.wait(timeout=2)
            return {"roots": []}
        finally:
            finished.set()

    request = asyncio.create_task(flight.run(project))
    assert await asyncio.to_thread(started.wait, 1)
    request.cancel()
    with suppress(asyncio.CancelledError):
        await request

    with pytest.raises(_SnapshotBusyError):
        await flight.run(lambda: {"roots": []})

    release.set()
    assert await asyncio.to_thread(finished.wait, 1)
    await asyncio.sleep(0)
    assert await flight.run(lambda: {"roots": ["next"]}) == {"roots": ["next"]}
    assert calls == 1


def test_dashboard_snapshot_route_rejects_concurrent_store_work() -> None:
    started = threading.Event()
    release = threading.Event()
    calls = 0

    class BlockingStore:
        def get_dashboard_snapshot(self, **_kwargs: object) -> dict[str, object]:
            nonlocal calls
            calls += 1
            started.set()
            assert release.wait(timeout=2)
            return {"window_hours": 24, "roots": []}

    app = create_app(cast(Store, BlockingStore()))
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(client.get, "/dashboard/snapshot")
        assert started.wait(timeout=1)
        follower = client.get("/dashboard/snapshot")
        assert follower.status_code == 429
        assert follower.headers["retry-after"] == "1"
        assert calls == 1
        release.set()
        assert first.result(timeout=2).status_code == 200
        assert client.get("/dashboard/snapshot").status_code == 200

    assert calls == 2


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
