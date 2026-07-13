"""Daemon app WS message-status query and wait-until-delivery tests."""

from __future__ import annotations

from pathlib import Path

from app_helpers import (
    _build_app_with_store,
    _message_status,
    _peer_message,
    _register_ws,
    _start_message_status_wait,
    _unknown_message_status,
)
from fastapi.testclient import TestClient

from basecamp.hub.frames import PROTOCOL_VERSION
from basecamp.hub.swarm.service.messaging import MAX_MESSAGE_WAIT_TIMEOUT_SECONDS, _message_wait_timeout


def test_ws_message_status_immediate_authorized_and_unknown_for_missing_or_unauthorized(
    tmp_path: Path,
) -> None:
    app, store = _build_app_with_store(tmp_path)
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="agent",
        session_name="root",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="target",
        agent_handle="target",
        parent_id="root",
        sibling_group="sg-target",
        depth=1,
        role="worker",
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
            _register_ws(sender_ws, node_id="root", role="agent", parent_id=None, sibling_group="sg-root")
            statuses = []
            for message_id in ["accepted-message", "sent-message", "queued-message", "missing-message"]:
                sender_ws.send_json(_message_status(message_id))
                statuses.append(sender_ws.receive_json())

        with client.websocket_connect("/ws") as outsider_ws:
            _register_ws(
                outsider_ws,
                node_id="outside-root",
                role="agent",
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
                _register_ws(sender_ws, node_id="root", role="agent", parent_id=None, sibling_group="sg-root")
                with client.websocket_connect("/ws") as target_ws:
                    _register_ws(
                        target_ws,
                        node_id="agent-1",
                        role="worker",
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
            role="worker",
            session_name="offline",
            cwd="/tmp/offline",
        )
        with client.websocket_connect("/ws") as sender_ws:
            _register_ws(sender_ws, node_id="root", role="agent", parent_id=None, sibling_group="sg-root")
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
        role="agent",
        session_name="root",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="target",
        agent_handle="target",
        parent_id="root",
        sibling_group="sg-target",
        depth=1,
        role="worker",
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
            _register_ws(sender_ws, node_id="root", role="agent", parent_id=None, sibling_group="sg-root")
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
