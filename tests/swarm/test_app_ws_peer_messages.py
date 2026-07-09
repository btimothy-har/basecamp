"""Daemon app WS peer-message acceptance and delivery-ack tests."""

from __future__ import annotations

import time
from pathlib import Path

from app_helpers import (
    _build_app_with_store,
    _message_count,
    _message_status,
    _peer_message,
    _register_ws,
    _wait_for_store_message_status,
)
from fastapi.testclient import TestClient

from basecamp.swarm.frames import PROTOCOL_VERSION


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
