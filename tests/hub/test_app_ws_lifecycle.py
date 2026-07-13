"""Daemon app WS registration lifecycle and health endpoint tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from app_helpers import _build_app, _register_ws
from fastapi.testclient import TestClient

from basecamp.hub.frames import PROTOCOL_VERSION


def test_health_endpoint(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "protocol": PROTOCOL_VERSION}


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


def test_ws_disconnect_schedules_disconnect_reaper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def record_schedule(**kwargs: object) -> None:
        calls.append(str(kwargs["node_id"]))

    monkeypatch.setattr("basecamp.hub.app.schedule_disconnect_reaper", record_schedule)
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            _register_ws(websocket, node_id="node-1", role="session", parent_id=None, sibling_group="sg-main")

    assert calls == ["node-1"]


def test_ws_reregister_cancels_disconnect_reaper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cancelled: list[str] = []

    def record_schedule(**_kwargs: object) -> None:
        return

    def record_cancel(_registry: object, node_id: str) -> None:
        cancelled.append(node_id)

    monkeypatch.setattr("basecamp.hub.app.schedule_disconnect_reaper", record_schedule)
    monkeypatch.setattr("basecamp.hub.registry.Registry.cancel_disconnect_reaper", record_cancel)
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as first:
            _register_ws(first, node_id="node-1", role="session", parent_id=None, sibling_group="sg-main")
        with client.websocket_connect("/ws") as second:
            _register_ws(second, node_id="node-1", role="session", parent_id=None, sibling_group="sg-main")

    assert cancelled == ["node-1", "node-1"]


def test_ws_duplicate_active_registration_is_rejected(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as first:
            first.send_json(
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
            assert first.receive_json()["type"] == "registered"

            with client.websocket_connect("/ws") as second:
                second.send_json(
                    {
                        "type": "register",
                        "v": PROTOCOL_VERSION,
                        "role": "session",
                        "node_id": "node-1",
                        "parent_id": None,
                        "sibling_group": None,
                        "depth": 0,
                        "session_name": "hijack-attempt",
                        "cwd": "/tmp/other",
                    }
                )
                reply = second.receive_json()

    assert reply["type"] == "error"
    assert reply["code"] == "duplicate_node_connection"


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


def test_health_returns_protocol_21(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["protocol"] == 21
