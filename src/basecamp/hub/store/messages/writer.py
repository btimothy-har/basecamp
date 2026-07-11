"""Writes for the ``messages`` table: peer-message lifecycle transitions."""

from __future__ import annotations

from .schema import (
    MESSAGE_STATUS_ACCEPTED,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_QUEUED,
    MESSAGE_STATUS_SENT,
    MESSAGE_STATUS_UNAVAILABLE,
)


class MessagesWriterMixin:
    """Peer-message persistence mutations."""

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
