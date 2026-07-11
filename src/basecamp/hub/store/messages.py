"""Peer-message persistence mixin and message status constants."""

from __future__ import annotations

import sqlite3
from typing import Any

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


class MessagesMixin:
    """Peer-message persistence operations."""

    def create_message(
        self,
        *,
        message_id: str,
        root_id: str,
        sender_node_id: str,
        sender_handle: str | None,
        target_agent_id: str,
        target_handle: str,
        content: str,
        interrupt: bool,
    ) -> None:
        """Persist a newly accepted peer message."""

        with self._connect() as connection:
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
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    root_id,
                    sender_node_id,
                    sender_handle,
                    target_agent_id,
                    target_handle,
                    content,
                    1 if interrupt else 0,
                    MESSAGE_STATUS_ACCEPTED,
                    self._now(),
                ),
            )

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        """Fetch a peer message by id as a dict, or None when absent."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
            return dict(row) if row is not None else None

    def mark_message_sent(self, message_id: str) -> bool:
        """Mark a non-terminal peer message as sent."""

        sent_at = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE messages
                SET status = ?, sent_at = ?
                WHERE id = ?
                  AND status NOT IN (?, ?, ?)
                """,
                (
                    MESSAGE_STATUS_SENT,
                    sent_at,
                    message_id,
                    MESSAGE_STATUS_QUEUED,
                    MESSAGE_STATUS_FAILED,
                    MESSAGE_STATUS_UNAVAILABLE,
                ),
            )
            return cursor.rowcount > 0

    def mark_message_queued(self, message_id: str) -> bool:
        """Mark a non-terminal peer message as queued for recipient handling."""

        queued_at = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE messages
                SET status = ?, queued_at = ?, error = NULL
                WHERE id = ?
                  AND status IN (?, ?)
                """,
                (
                    MESSAGE_STATUS_QUEUED,
                    queued_at,
                    message_id,
                    MESSAGE_STATUS_ACCEPTED,
                    MESSAGE_STATUS_SENT,
                ),
            )
            return cursor.rowcount > 0

    def mark_message_failed(self, message_id: str, error: str | None = None) -> bool:
        """Mark a non-terminal peer message as failed."""

        failed_at = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE messages
                SET status = ?, failed_at = ?, error = ?
                WHERE id = ?
                  AND status IN (?, ?)
                """,
                (
                    MESSAGE_STATUS_FAILED,
                    failed_at,
                    error,
                    message_id,
                    MESSAGE_STATUS_ACCEPTED,
                    MESSAGE_STATUS_SENT,
                ),
            )
            return cursor.rowcount > 0

    def mark_message_unavailable(self, message_id: str, error: str | None = None) -> bool:
        """Mark a non-terminal peer message as unavailable for this phase."""

        failed_at = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE messages
                SET status = ?, failed_at = ?, error = ?
                WHERE id = ?
                  AND status IN (?, ?)
                """,
                (
                    MESSAGE_STATUS_UNAVAILABLE,
                    failed_at,
                    error,
                    message_id,
                    MESSAGE_STATUS_ACCEPTED,
                    MESSAGE_STATUS_SENT,
                ),
            )
            return cursor.rowcount > 0

    def get_message_status(self, requester_node_id: str, message_id: str) -> dict[str, Any]:
        """Return the public delivery status for a participant-visible peer message."""

        unknown = {
            "message_id": message_id,
            "status": MESSAGE_STATUS_UNKNOWN,
            "error": None,
            "created_at": None,
            "sent_at": None,
            "queued_at": None,
            "failed_at": None,
        }

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT
                    sender_node_id,
                    target_agent_id,
                    status,
                    error,
                    created_at,
                    sent_at,
                    queued_at,
                    failed_at
                FROM messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()

        if row is None:
            return unknown

        if requester_node_id not in {row["sender_node_id"], row["target_agent_id"]}:
            return unknown

        status = row["status"]
        if status not in MESSAGE_STATUSES:
            return unknown

        return {
            "message_id": message_id,
            "status": status,
            "error": row["error"],
            "created_at": row["created_at"],
            "sent_at": row["sent_at"],
            "queued_at": row["queued_at"],
            "failed_at": row["failed_at"],
        }
