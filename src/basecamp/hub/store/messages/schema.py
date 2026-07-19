"""Schema for the ``messages`` table, plus peer-message status constants."""

from __future__ import annotations

import sqlite3

MESSAGE_STATUS_ACCEPTED = "accepted"
MESSAGE_STATUS_SENT = "sent"
MESSAGE_STATUS_QUEUED = "queued"
MESSAGE_STATUS_FAILED = "failed"
MESSAGE_STATUS_UNAVAILABLE = "unavailable"
MESSAGE_STATUS_UNKNOWN = "unknown"
MESSAGE_STATUSES = (
    MESSAGE_STATUS_ACCEPTED,
    MESSAGE_STATUS_SENT,
    MESSAGE_STATUS_QUEUED,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_UNAVAILABLE,
)
MESSAGE_TERMINAL_DELIVERY_STATUSES = (
    MESSAGE_STATUS_QUEUED,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_UNAVAILABLE,
    MESSAGE_STATUS_UNKNOWN,
)


class MessagesSchemaMixin:
    """Create the ``messages`` table."""

    def _init_messages_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                root_id TEXT,
                sender_node_id TEXT,
                sender_handle TEXT,
                target_agent_id TEXT,
                target_handle TEXT,
                content TEXT,
                interrupt INTEGER,
                status TEXT CHECK(status IN ('accepted','sent','queued','failed','unavailable')),
                error TEXT,
                created_at TEXT,
                sent_at TEXT,
                queued_at TEXT,
                failed_at TEXT
            )
            """
        )
