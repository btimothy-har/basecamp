"""Tests for daemon store peer-message persistence and delivery status."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from basecamp.swarm.store import Store, is_message_delivery_terminal
from store_helpers import _create_message, _unknown_message_status


def test_create_message_persists_accepted_message(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.create_message(
        message_id="message-1",
        root_id="root-1",
        sender_node_id="sender-1",
        sender_handle=None,
        target_agent_id="target-1",
        target_handle="target-handle",
        content="hello peer",
        interrupt=True,
    )

    message = store.get_message("message-1")

    assert message is not None
    assert message["id"] == "message-1"
    assert message["root_id"] == "root-1"
    assert message["sender_node_id"] == "sender-1"
    assert message["sender_handle"] is None
    assert message["target_agent_id"] == "target-1"
    assert message["target_handle"] == "target-handle"
    assert message["content"] == "hello peer"
    assert message["interrupt"] == 1
    assert message["status"] == "accepted"
    assert message["error"] is None
    assert message["created_at"] is not None
    assert message["sent_at"] is None
    assert message["queued_at"] is None
    assert message["failed_at"] is None


def test_message_lifecycle_transitions_and_missing_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    _create_message(store, "sent-message")
    _create_message(store, "queued-message")
    _create_message(store, "failed-message")
    _create_message(store, "unavailable-message")

    assert store.mark_message_sent("sent-message") is True
    assert store.mark_message_queued("queued-message") is True
    assert store.mark_message_failed("failed-message", "delivery failed") is True
    assert store.mark_message_unavailable("unavailable-message", "target missing") is True
    assert store.mark_message_sent("missing-message") is False
    assert store.mark_message_queued("missing-message") is False
    assert store.mark_message_failed("missing-message", "missing") is False
    assert store.mark_message_unavailable("missing-message", "missing") is False

    sent = store.get_message("sent-message")
    queued = store.get_message("queued-message")
    failed = store.get_message("failed-message")
    unavailable = store.get_message("unavailable-message")

    assert sent is not None
    assert sent["status"] == "sent"
    assert sent["sent_at"] is not None
    assert queued is not None
    assert queued["status"] == "queued"
    assert queued["queued_at"] is not None
    assert queued["error"] is None
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["failed_at"] is not None
    assert failed["error"] == "delivery failed"
    assert unavailable is not None
    assert unavailable["status"] == "unavailable"
    assert unavailable["failed_at"] is not None
    assert unavailable["error"] == "target missing"


def test_message_terminal_states_do_not_get_overwritten(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    for message_id in ["queued-message", "failed-message", "unavailable-message"]:
        _create_message(store, message_id)

    assert store.mark_message_queued("queued-message") is True
    assert store.mark_message_failed("failed-message", "failed") is True
    assert store.mark_message_unavailable("unavailable-message", "unavailable") is True

    assert store.mark_message_sent("queued-message") is False
    assert store.mark_message_failed("queued-message", "late failure") is False
    assert store.mark_message_unavailable("queued-message", "late unavailable") is False
    assert store.mark_message_sent("failed-message") is False
    assert store.mark_message_queued("failed-message") is False
    assert store.mark_message_unavailable("failed-message", "late unavailable") is False
    assert store.mark_message_sent("unavailable-message") is False
    assert store.mark_message_queued("unavailable-message") is False
    assert store.mark_message_failed("unavailable-message", "late failure") is False

    queued = store.get_message("queued-message")
    failed = store.get_message("failed-message")
    unavailable = store.get_message("unavailable-message")

    assert queued is not None
    assert queued["status"] == "queued"
    assert queued["sent_at"] is None
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["sent_at"] is None
    assert unavailable is not None
    assert unavailable["status"] == "unavailable"
    assert unavailable["sent_at"] is None


def test_get_message_status_authorizes_participants_only(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)
    _create_message(store, "message-1")
    assert store.mark_message_failed("message-1", "delivery failed") is True

    sender_status = store.get_message_status("sender-1", "message-1")
    recipient_status = store.get_message_status("target-1", "message-1")
    missing_status = store.get_message_status("sender-1", "missing-message")
    unauthorized_status = store.get_message_status("root-1", "message-1")

    assert sender_status == recipient_status
    assert sender_status["message_id"] == "message-1"
    assert sender_status["status"] == "failed"
    assert sender_status["error"] == "delivery failed"
    assert sender_status["created_at"] is not None
    assert sender_status["failed_at"] is not None
    assert sender_status["sent_at"] is None
    assert sender_status["queued_at"] is None
    assert missing_status == _unknown_message_status("missing-message")
    assert unauthorized_status == _unknown_message_status("message-1")


def test_get_message_status_hides_malformed_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    Store(db_path=db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            """
            INSERT INTO messages (
                id,
                root_id,
                sender_node_id,
                sender_handle,
                target_agent_id,
                target_handle,
                content,
                interrupt,
                status,
                error,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "malformed-message",
                "root-1",
                "sender-1",
                "sender",
                "target-1",
                "target",
                "secret",
                0,
                "bogus",
                "secret error",
                "2026-01-01T00:00:00Z",
            ),
        )

    store = Store(db_path=db_path)

    assert store.get_message_status("sender-1", "malformed-message") == _unknown_message_status("malformed-message")


def test_is_message_delivery_terminal() -> None:
    assert is_message_delivery_terminal("queued") is True
    assert is_message_delivery_terminal("failed") is True
    assert is_message_delivery_terminal("unavailable") is True
    assert is_message_delivery_terminal("unknown") is True
    assert is_message_delivery_terminal("accepted") is False
    assert is_message_delivery_terminal("sent") is False
