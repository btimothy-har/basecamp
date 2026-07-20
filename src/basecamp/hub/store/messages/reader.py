"""Reads for the ``messages`` table."""

from __future__ import annotations

from typing import Any

from .schema import MESSAGE_STATUS_UNKNOWN, MESSAGE_STATUSES


class MessagesReaderMixin:
    """Peer-message queries."""

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        """Fetch a peer message by id as a dict, or None when absent."""

        with self._reading() as connection:
            row = connection.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
            return dict(row) if row is not None else None

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

        with self._reading() as connection:
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
