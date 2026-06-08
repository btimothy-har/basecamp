"""Tests for daemon HTTP and WebSocket skeleton behavior."""

from __future__ import annotations

from pathlib import Path

from basecamp.daemon.app import create_app
from basecamp.daemon.store import Store
from fastapi.testclient import TestClient


def _build_app(tmp_path: Path):
    store = Store(db_path=tmp_path / "daemon.db")
    return create_app(store)


def test_health_endpoint(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "protocol": 1}


def test_ws_register_returns_registered(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "register",
                    "v": 1,
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
        "v": 1,
        "node_id": "node-1",
        "protocol": 1,
    }


def test_ws_version_mismatch_returns_protocol_error(tmp_path: Path) -> None:
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
                    "sibling_group": None,
                    "depth": 0,
                    "session_name": "test-session",
                    "cwd": "/tmp/project",
                }
            )
            reply = websocket.receive_json()

    assert reply["type"] == "error"
    assert reply["v"] == 1
    assert reply["code"] == "protocol_version"
