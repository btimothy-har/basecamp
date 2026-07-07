"""Tests for daemon HTTP and WebSocket skeleton behavior."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pi_swarm.app import create_app
from pi_swarm.frames import PROTOCOL_VERSION
from pi_swarm.service import MAX_MESSAGE_WAIT_TIMEOUT_SECONDS, _message_wait_timeout
from pi_swarm.store import Store


def _build_app(tmp_path: Path):
    store = Store(db_path=tmp_path / "daemon.db", task_dir=tmp_path / "tasks")
    return create_app(store)


def _build_app_with_store(tmp_path: Path):
    store = Store(db_path=tmp_path / "daemon.db", task_dir=tmp_path / "tasks")
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
                            "task": "a1",
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
                            "task": "a2",
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
                            "task": "a2",
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


def test_ws_disconnect_schedules_disconnect_reaper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def record_schedule(**kwargs: object) -> None:
        calls.append(str(kwargs["node_id"]))

    monkeypatch.setattr("pi_swarm.app.schedule_disconnect_reaper", record_schedule)
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

    monkeypatch.setattr("pi_swarm.app.schedule_disconnect_reaper", record_schedule)
    monkeypatch.setattr("pi_swarm.registry.Registry.cancel_disconnect_reaper", record_cancel)
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


def test_ws_cancel_unknown_handle_returns_not_found_ack(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            _register_ws(websocket, node_id="root", role="session", parent_id=None, sibling_group="sg-root")
            websocket.send_json(
                {
                    "type": "cancel",
                    "v": PROTOCOL_VERSION,
                    "request_id": "cancel-missing",
                    "target_handle": "missing-handle",
                }
            )
            reply = websocket.receive_json()

    assert reply == {
        "type": "cancel_ack",
        "v": PROTOCOL_VERSION,
        "request_id": "cancel-missing",
        "status": "not_found",
        "error": None,
    }


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


def test_runs_summary_endpoint_returns_child_agents(tmp_path: Path) -> None:
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


def test_ws_peer_message_ack_is_immediate_and_delivery_is_forwarded(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as sender_ws:
            _register_ws(sender_ws, node_id="root", role="session", parent_id=None, sibling_group="sg-root")
            with client.websocket_connect("/ws") as target_ws:
                _register_ws(
                    target_ws,
                    node_id="agent-1",
                    role="agent",
                    parent_id="root",
                    sibling_group="sg-agent",
                    agent_handle="target",
                )

                sender_ws.send_json(_peer_message("request-1", target_handle="target", message="hello", interrupt=True))
                ack = sender_ws.receive_json()

                assert ack["type"] == "peer_message_ack"
                assert ack["request_id"] == "request-1"
                assert ack["status"] == "accepted"
                assert ack["error"] is None
                assert isinstance(ack["message_id"], str)

                delivery = target_ws.receive_json()
                assert delivery == {
                    "type": "peer_message_delivery",
                    "v": PROTOCOL_VERSION,
                    "message_id": ack["message_id"],
                    "from_handle": None,
                    "from_relation": "parent",
                    "message": "hello",
                    "interrupt": True,
                }

    message = _wait_for_store_message_status(store, ack["message_id"], "sent")
    assert message["status"] == "sent"
    assert message["sent_at"] is not None
    assert message["queued_at"] is None


def test_ws_peer_message_sessions_and_agents_are_messageable_by_public_handle(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as root_ws:
            _register_ws(
                root_ws,
                node_id="root",
                role="session",
                parent_id=None,
                sibling_group="sg-root",
                agent_handle="root-handle",
            )
            with client.websocket_connect("/ws") as agent_ws:
                _register_ws(
                    agent_ws,
                    node_id="agent-1",
                    role="agent",
                    parent_id="root",
                    sibling_group="root",
                    agent_handle="agent-handle",
                )

                agent_ws.send_json(_peer_message("request-agent-root", target_handle="root-handle", message="to root"))
                agent_to_root_ack = agent_ws.receive_json()
                root_delivery = root_ws.receive_json()

                root_ws.send_json(_peer_message("request-root-agent", target_handle="agent-handle", message="to agent"))
                root_to_agent_ack = root_ws.receive_json()
                agent_delivery = agent_ws.receive_json()

    assert agent_to_root_ack["status"] == "accepted"
    assert root_delivery == {
        "type": "peer_message_delivery",
        "v": PROTOCOL_VERSION,
        "message_id": agent_to_root_ack["message_id"],
        "from_handle": "agent-handle",
        "from_relation": "child",
        "from_product_role": "subagent",
        "message": "to root",
        "interrupt": False,
    }
    assert root_to_agent_ack["status"] == "accepted"
    assert agent_delivery == {
        "type": "peer_message_delivery",
        "v": PROTOCOL_VERSION,
        "message_id": root_to_agent_ack["message_id"],
        "from_handle": "root-handle",
        "from_relation": "parent",
        "message": "to agent",
        "interrupt": False,
    }
    agent_to_root_message = _wait_for_store_message_status(store, agent_to_root_ack["message_id"], "sent")
    root_to_agent_message = _wait_for_store_message_status(store, root_to_agent_ack["message_id"], "sent")
    assert agent_to_root_message["target_handle"] == "root-handle"
    assert root_to_agent_message["sender_handle"] == "root-handle"


def test_ws_peer_message_agent_without_public_handle_delivers_null_from_handle(tmp_path: Path) -> None:
    app, _store = _build_app_with_store(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as root_ws:
            _register_ws(root_ws, node_id="root", role="session", parent_id=None, sibling_group="sg-root")
            with client.websocket_connect("/ws") as sender_ws:
                _register_ws(
                    sender_ws,
                    node_id="sender-private-id",
                    role="agent",
                    parent_id="root",
                    sibling_group="root",
                )
                with client.websocket_connect("/ws") as target_ws:
                    _register_ws(
                        target_ws,
                        node_id="agent-1",
                        role="agent",
                        parent_id="root",
                        sibling_group="root",
                        agent_handle="target",
                    )
                    sender_ws.send_json(
                        _peer_message("request-private-sender", target_handle="target", message="hello")
                    )
                    message_id = sender_ws.receive_json()["message_id"]
                    delivery = target_ws.receive_json()

    assert delivery["message_id"] == message_id
    assert delivery["from_handle"] is None
    assert delivery["from_relation"] == "peer"


def test_ws_peer_message_delivery_ack_queued_updates_status(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as sender_ws:
            _register_ws(sender_ws, node_id="root", role="session", parent_id=None, sibling_group="sg-root")
            with client.websocket_connect("/ws") as target_ws:
                _register_ws(
                    target_ws,
                    node_id="agent-1",
                    role="agent",
                    parent_id="root",
                    sibling_group="sg-agent",
                    agent_handle="target",
                )
                sender_ws.send_json(_peer_message("request-queued", target_handle="target", message="queue me"))
                message_id = sender_ws.receive_json()["message_id"]
                target_ws.receive_json()

                target_ws.send_json(
                    {
                        "type": "peer_message_delivery_ack",
                        "v": PROTOCOL_VERSION,
                        "message_id": message_id,
                        "status": "queued",
                        "error": None,
                    }
                )
                _wait_for_store_message_status(store, message_id, "queued")

                sender_ws.send_json(_message_status(message_id))
                status = sender_ws.receive_json()

    assert status["type"] == "message_status_result"
    assert status["message_id"] == message_id
    assert status["status"] == "queued"
    assert status["error"] is None
    assert status["created_at"] is not None
    assert status["sent_at"] is not None
    assert status["queued_at"] is not None
    assert status["failed_at"] is None


def test_ws_peer_message_delivery_ack_failed_updates_status_and_error(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as sender_ws:
            _register_ws(sender_ws, node_id="root", role="session", parent_id=None, sibling_group="sg-root")
            with client.websocket_connect("/ws") as target_ws:
                _register_ws(
                    target_ws,
                    node_id="agent-1",
                    role="agent",
                    parent_id="root",
                    sibling_group="sg-agent",
                    agent_handle="target",
                )
                sender_ws.send_json(_peer_message("request-failed", target_handle="target", message="fail me"))
                message_id = sender_ws.receive_json()["message_id"]
                target_ws.receive_json()

                target_ws.send_json(
                    {
                        "type": "peer_message_delivery_ack",
                        "v": PROTOCOL_VERSION,
                        "message_id": message_id,
                        "status": "failed",
                        "error": "recipient failed",
                    }
                )
                _wait_for_store_message_status(store, message_id, "failed")

                target_ws.send_json(_message_status(message_id))
                status = target_ws.receive_json()

    assert status["status"] == "failed"
    assert status["error"] == "recipient failed"
    assert status["failed_at"] is not None


def test_ws_peer_message_unavailable_without_live_target_and_wait_returns_unavailable(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)
    store.upsert_agent(
        agent_id="agent-1",
        agent_handle="target",
        parent_id="root",
        sibling_group="sg-agent",
        depth=1,
        role="agent",
        session_name="target",
        cwd="/tmp/target",
    )

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as sender_ws:
            _register_ws(sender_ws, node_id="root", role="session", parent_id=None, sibling_group="sg-root")

            sender_ws.send_json(_peer_message("request-unavailable", target_handle="target", message="hello"))
            ack = sender_ws.receive_json()
            assert ack["status"] == "accepted"

            sender_ws.send_json(_message_status(ack["message_id"], wait_until_delivery=True, timeout_s=1))
            status = sender_ws.receive_json()

    assert status["status"] == "unavailable"
    assert status["failed_at"] is not None
    assert store.get_message(ack["message_id"])["status"] == "unavailable"


def test_ws_peer_message_known_handle_is_contactable_while_missing_and_private_id_stay_unknown(
    tmp_path: Path,
) -> None:
    app, store = _build_app_with_store(tmp_path)
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group="outside-root",
        depth=0,
        role="session",
        session_name="outside-root",
        cwd="/tmp/outside-root",
    )
    store.upsert_agent(
        agent_id="outside-agent",
        agent_handle="outside",
        parent_id="outside-root",
        sibling_group="outside-root",
        depth=1,
        role="agent",
        session_name="outside",
        cwd="/tmp/outside",
    )
    store.upsert_agent(
        agent_id="private-agent-id",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="private-agent",
        cwd="/tmp/private-agent",
    )

    before_messages = _message_count(store)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as sender_ws:
            _register_ws(sender_ws, node_id="root", role="session", parent_id=None, sibling_group="sg-root")

            sender_ws.send_json(_peer_message("request-missing", target_handle="missing", message="hello"))
            missing = sender_ws.receive_json()
            # A valid public handle on an otherwise-unrelated root is a routable
            # contact address, so this is accepted even without reachability.
            sender_ws.send_json(_peer_message("request-outside", target_handle="outside", message="hello"))
            known_handle = sender_ws.receive_json()
            # Addressing by private agent id (handle == id) is not a public handle
            # and stays non-leaky.
            sender_ws.send_json(_peer_message("request-private", target_handle="private-agent-id", message="hello"))
            private_fallback = sender_ws.receive_json()

    after_messages = _message_count(store)

    assert missing == {
        "type": "peer_message_ack",
        "v": PROTOCOL_VERSION,
        "request_id": "request-missing",
        "message_id": None,
        "status": "unknown",
        "error": None,
    }
    assert known_handle["type"] == "peer_message_ack"
    assert known_handle["request_id"] == "request-outside"
    assert known_handle["status"] == "accepted"
    assert known_handle["message_id"] is not None
    assert private_fallback == {
        "type": "peer_message_ack",
        "v": PROTOCOL_VERSION,
        "request_id": "request-private",
        "message_id": None,
        "status": "unknown",
        "error": None,
    }
    assert after_messages == before_messages + 1


def test_ws_message_status_immediate_authorized_and_unknown_for_missing_or_unauthorized(
    tmp_path: Path,
) -> None:
    app, store = _build_app_with_store(tmp_path)
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="target",
        agent_handle="target",
        parent_id="root",
        sibling_group="sg-target",
        depth=1,
        role="agent",
        session_name="target",
        cwd="/tmp/target",
    )
    for message_id in ["accepted-message", "sent-message", "queued-message"]:
        store.create_message(
            message_id=message_id,
            root_id="root",
            sender_node_id="root",
            sender_handle=None,
            target_agent_id="target",
            target_handle="target",
            content="hello",
            interrupt=False,
        )
    store.mark_message_sent("sent-message")
    store.mark_message_queued("queued-message")

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as sender_ws:
            _register_ws(sender_ws, node_id="root", role="session", parent_id=None, sibling_group="sg-root")
            statuses = []
            for message_id in ["accepted-message", "sent-message", "queued-message", "missing-message"]:
                sender_ws.send_json(_message_status(message_id))
                statuses.append(sender_ws.receive_json())

        with client.websocket_connect("/ws") as outsider_ws:
            _register_ws(
                outsider_ws,
                node_id="outside-root",
                role="session",
                parent_id=None,
                sibling_group="outside-root",
            )
            outsider_ws.send_json(_message_status("queued-message"))
            unauthorized = outsider_ws.receive_json()

    assert [status["status"] for status in statuses] == ["accepted", "sent", "queued", "unknown"]
    assert statuses[0]["created_at"] is not None
    assert statuses[1]["sent_at"] is not None
    assert statuses[2]["queued_at"] is not None
    assert statuses[3] == _unknown_message_status("missing-message")
    assert unauthorized == _unknown_message_status("queued-message")


def test_ws_message_status_wait_until_delivery_wakes_on_queued_failed_and_unavailable(
    tmp_path: Path,
) -> None:
    app, store = _build_app_with_store(tmp_path)

    with TestClient(app) as client:
        for terminal_status in ["queued", "failed"]:
            with client.websocket_connect("/ws") as sender_ws:
                _register_ws(sender_ws, node_id="root", role="session", parent_id=None, sibling_group="sg-root")
                with client.websocket_connect("/ws") as target_ws:
                    _register_ws(
                        target_ws,
                        node_id="agent-1",
                        role="agent",
                        parent_id="root",
                        sibling_group="sg-agent",
                        agent_handle="target",
                    )
                    sender_ws.send_json(
                        _peer_message(f"request-{terminal_status}", target_handle="target", message="hello")
                    )
                    message_id = sender_ws.receive_json()["message_id"]
                    target_ws.receive_json()

                    waiter = _start_message_status_wait(sender_ws, message_id, timeout_s=2)
                    waiter["sent"].wait(timeout=1)
                    target_ws.send_json(
                        {
                            "type": "peer_message_delivery_ack",
                            "v": PROTOCOL_VERSION,
                            "message_id": message_id,
                            "status": terminal_status,
                            "error": "boom" if terminal_status == "failed" else None,
                        }
                    )
                    waiter["thread"].join(timeout=2)
                    assert not waiter["thread"].is_alive()
                    assert waiter["result"]["status"] == terminal_status

        store.upsert_agent(
            agent_id="offline-agent",
            agent_handle="offline",
            parent_id="root",
            sibling_group="sg-offline",
            depth=1,
            role="agent",
            session_name="offline",
            cwd="/tmp/offline",
        )
        with client.websocket_connect("/ws") as sender_ws:
            _register_ws(sender_ws, node_id="root", role="session", parent_id=None, sibling_group="sg-root")
            sender_ws.send_json(_peer_message("request-offline", target_handle="offline", message="hello"))
            message_id = sender_ws.receive_json()["message_id"]
            sender_ws.send_json(_message_status(message_id, wait_until_delivery=True, timeout_s=2))
            unavailable = sender_ws.receive_json()

    assert unavailable["status"] == "unavailable"


def test_ws_message_status_wait_until_delivery_timeout_returns_current_nonterminal_status(
    tmp_path: Path,
) -> None:
    app, store = _build_app_with_store(tmp_path)
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="target",
        agent_handle="target",
        parent_id="root",
        sibling_group="sg-target",
        depth=1,
        role="agent",
        session_name="target",
        cwd="/tmp/target",
    )
    store.create_message(
        message_id="accepted-message",
        root_id="root",
        sender_node_id="root",
        sender_handle=None,
        target_agent_id="target",
        target_handle="target",
        content="hello",
        interrupt=False,
    )
    store.create_message(
        message_id="sent-message",
        root_id="root",
        sender_node_id="root",
        sender_handle=None,
        target_agent_id="target",
        target_handle="target",
        content="hello",
        interrupt=False,
    )
    store.mark_message_sent("sent-message")

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as sender_ws:
            _register_ws(sender_ws, node_id="root", role="session", parent_id=None, sibling_group="sg-root")
            sender_ws.send_json(_message_status("accepted-message", wait_until_delivery=True, timeout_s=0.01))
            accepted = sender_ws.receive_json()
            sender_ws.send_json(_message_status("sent-message", wait_until_delivery=True, timeout_s=-1))
            sent = sender_ws.receive_json()

    assert accepted["status"] == "accepted"
    assert sent["status"] == "sent"


def test_message_wait_timeout_bounds_caller_input() -> None:
    assert _message_wait_timeout(None) == 30.0
    assert _message_wait_timeout(-1) == 0.0
    assert _message_wait_timeout(float("nan")) == 0.0
    assert _message_wait_timeout(float("-inf")) == 0.0
    assert _message_wait_timeout(float("inf")) == MAX_MESSAGE_WAIT_TIMEOUT_SECONDS
    assert _message_wait_timeout(MAX_MESSAGE_WAIT_TIMEOUT_SECONDS + 1) == MAX_MESSAGE_WAIT_TIMEOUT_SECONDS


def test_ws_peer_message_delivery_ack_from_non_target_is_ignored(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as sender_ws:
            _register_ws(sender_ws, node_id="root", role="session", parent_id=None, sibling_group="sg-root")
            with client.websocket_connect("/ws") as target_ws:
                _register_ws(
                    target_ws,
                    node_id="agent-1",
                    role="agent",
                    parent_id="root",
                    sibling_group="sg-agent",
                    agent_handle="target",
                )
                with client.websocket_connect("/ws") as other_ws:
                    _register_ws(
                        other_ws,
                        node_id="other-agent",
                        role="agent",
                        parent_id="root",
                        sibling_group="sg-other",
                        agent_handle="other",
                    )
                    sender_ws.send_json(_peer_message("request-auth", target_handle="target", message="hello"))
                    message_id = sender_ws.receive_json()["message_id"]
                    target_ws.receive_json()
                    _wait_for_store_message_status(store, message_id, "sent")

                    other_ws.send_json(
                        {
                            "type": "peer_message_delivery_ack",
                            "v": PROTOCOL_VERSION,
                            "message_id": message_id,
                            "status": "queued",
                            "error": None,
                        }
                    )
                    time.sleep(0.05)

    assert store.get_message(message_id)["status"] == "sent"


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
        role="session",
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
            role="agent",
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
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="agent",
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
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="agent",
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
                    {"label": "Done", "description": "d", "notes": None, "status": "completed"},
                    {"label": 123, "description": "bad", "notes": None, "status": "completed"},
                    {"label": "Current", "description": "desc", "notes": "notes", "status": "active"},
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
            "notes": "notes",
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


def _register_ws(
    websocket,
    *,
    node_id: str,
    role: str,
    parent_id: str | None,
    sibling_group: str | None,
    agent_handle: str | None = None,
) -> None:
    payload = {
        "type": "register",
        "v": PROTOCOL_VERSION,
        "role": role,
        "node_id": node_id,
        "parent_id": parent_id,
        "sibling_group": sibling_group,
        "depth": 0 if role == "session" else 1,
        "session_name": node_id,
        "cwd": f"/tmp/{node_id}",
    }
    if agent_handle is not None:
        payload["agent_handle"] = agent_handle
    websocket.send_json(payload)
    assert websocket.receive_json()["type"] == "registered"


def _peer_message(
    request_id: str,
    *,
    target_handle: str,
    message: str,
    interrupt: bool = False,
) -> dict[str, object]:
    return {
        "type": "peer_message",
        "v": PROTOCOL_VERSION,
        "request_id": request_id,
        "target_handle": target_handle,
        "message": message,
        "interrupt": interrupt,
    }


def _message_count(store: Store) -> int:
    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM messages").fetchone()
    assert row is not None
    return int(row[0])


def _message_status(
    message_id: str,
    *,
    request_id: str | None = None,
    wait_until_delivery: bool = False,
    timeout_s: float | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "message_status",
        "v": PROTOCOL_VERSION,
        "request_id": request_id or f"request-status-{message_id}",
        "message_id": message_id,
        "wait_until_delivery": wait_until_delivery,
    }
    if timeout_s is not None:
        payload["timeout_s"] = timeout_s
    return payload


def _start_message_status_wait(websocket, message_id: str, *, timeout_s: float) -> dict[str, object]:
    result: dict[str, object] = {}
    sent = threading.Event()

    def wait_for_status() -> None:
        websocket.send_json(_message_status(message_id, wait_until_delivery=True, timeout_s=timeout_s))
        sent.set()
        result.update(websocket.receive_json())

    thread = threading.Thread(target=wait_for_status)
    thread.start()
    return {"thread": thread, "sent": sent, "result": result}


def _wait_for_store_message_status(store: Store, message_id: str, status: str) -> dict[str, object]:
    deadline = time.time() + 2
    message = None
    while time.time() < deadline:
        message = store.get_message(message_id)
        if message is not None and message["status"] == status:
            return message
        time.sleep(0.01)
    assert message is not None
    assert message["status"] == status
    return message


def _unknown_message_status(message_id: str, request_id: str | None = None) -> dict[str, object]:
    return {
        "type": "message_status_result",
        "v": PROTOCOL_VERSION,
        "request_id": request_id or f"request-status-{message_id}",
        "message_id": message_id,
        "status": "unknown",
        "error": None,
        "created_at": None,
        "sent_at": None,
        "queued_at": None,
        "failed_at": None,
    }


def _write_task_log(task_dir: Path, agent_id: str, cycles: list[dict[str, object]]) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / f"{agent_id}.json").write_text(json.dumps(cycles), encoding="utf-8")


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
        connection.execute(
            "UPDATE agents SET current_run_id = ? WHERE id = ?",
            (run_id, agent_id),
        )
