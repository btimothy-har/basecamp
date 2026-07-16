"""The ``episodes`` data object: one row per SessionStart→SessionEnd engagement.

An episode is the liveness unit. ``open_episode`` runs on every SessionStart and
``close_episode`` on every SessionEnd, so the durable ``sessions`` row is never
"ended" — which is what lets the hook stop special-casing ``clear``/``resume``
(each fires a SessionEnd that closes the current episode and a SessionStart that
opens the next). ``source`` records why an episode began and ``end_reason`` why it
ended, the diagnostic the old continuation-skip discarded.
"""

from __future__ import annotations

import sqlite3
import uuid


class EpisodesMixin:
    """Engagement intervals that carry a session's liveness."""

    def _init_episodes_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                source TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                end_reason TEXT
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_episodes_session_open ON episodes(session_id, ended_at)")

    def open_episode(self, *, session_id: str, source: str | None = None) -> str:
        """Open a fresh episode for a session and return its id.

        Any already-open episode for the session is closed first (``end_reason``
        left NULL): a SessionStart with no paired SessionEnd — e.g. ``compact``, or a
        crashed prior process — must not leave two live episodes. This keeps the
        one-open-episode-per-session invariant that ``list_open_sessions`` relies on.
        """

        now = self._now()
        episode_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "UPDATE episodes SET ended_at = ? WHERE session_id = ? AND ended_at IS NULL",
                (now, session_id),
            )
            connection.execute(
                """
                INSERT INTO episodes (id, session_id, source, started_at, ended_at, end_reason)
                VALUES (?, ?, ?, ?, NULL, NULL)
                """,
                (episode_id, session_id, source, now),
            )
            connection.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE session_id = ?",
                (now, session_id),
            )
        return episode_id

    def current_episode_id(self, *, session_id: str) -> str | None:
        """Return the id of the session's open episode, or ``None`` if none is open.

        Best-effort tag for transcript nodes ingested during this engagement. The
        ingest route resolves it *before* scheduling the background parse so a node
        first seen at SessionEnd is still tagged with the episode that just ended.
        """

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM episodes
                WHERE session_id = ? AND ended_at IS NULL
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        return row[0] if row else None

    def close_episode(self, *, session_id: str, reason: str | None = None) -> bool:
        """Close the session's open episode; return whether one was closed.

        Stamps ``ended_at``/``end_reason`` on the (single) open episode and refreshes
        the session's ``last_seen_at``. Returns ``False`` when the session has no open
        episode — an unknown id, or a SessionEnd already reconciled.
        """

        now = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE episodes SET ended_at = ?, end_reason = ?
                WHERE session_id = ? AND ended_at IS NULL
                """,
                (now, reason, session_id),
            )
            if cursor.rowcount > 0:
                connection.execute(
                    "UPDATE sessions SET last_seen_at = ? WHERE session_id = ?",
                    (now, session_id),
                )
            return cursor.rowcount > 0
