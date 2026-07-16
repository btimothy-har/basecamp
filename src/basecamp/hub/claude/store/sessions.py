"""The ``sessions`` data object: the durable per-actor identity row.

A session is keyed by the native ``CLAUDE_CODE_SESSION_ID``, which is stable
across resume and ``/clear``, so this row is written once and refreshed — never
"ended". Liveness lives entirely in :mod:`episodes`; ``list_open_sessions`` joins
to the open episode to report which sessions are currently live.
"""

from __future__ import annotations

import sqlite3
from typing import Any


class SessionsMixin:
    """Durable identity for hook-registered Claude Code sessions."""

    def _init_sessions_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                repo TEXT,
                worktree_label TEXT,
                handle TEXT UNIQUE,
                cwd TEXT,
                transcript_path TEXT,
                created_at TEXT,
                last_seen_at TEXT
            )
            """
        )

    def upsert_session(
        self,
        *,
        session_id: str,
        cwd: str,
        transcript_path: str | None = None,
        repo: str | None = None,
        worktree_label: str | None = None,
        handle: str | None = None,
    ) -> None:
        """Register (or refresh) a session's durable identity.

        Re-registering the same id — a resume or ``/clear`` — refreshes its facets
        and ``last_seen_at`` while preserving the original ``created_at``. Liveness is
        not touched here: opening/closing episodes is the caller's separate step.
        """

        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (
                    session_id, repo, worktree_label, handle, cwd,
                    transcript_path, created_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    repo = excluded.repo,
                    worktree_label = excluded.worktree_label,
                    handle = excluded.handle,
                    cwd = excluded.cwd,
                    transcript_path = excluded.transcript_path,
                    last_seen_at = excluded.last_seen_at
                """,
                (session_id, repo, worktree_label, handle, cwd, transcript_path, now, now),
            )

    def get_transcript_path(self, session_id: str) -> str | None:
        """Return the stored transcript path for a session, or ``None`` if unknown.

        The ingest route falls back to this when the hook payload omits the path (a
        SessionEnd hook carries no ``transcript_path``); the path is captured once at
        SessionStart and is stable for the session's lifetime.
        """

        with self._connect() as connection:
            row = connection.execute(
                "SELECT transcript_path FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row[0] if row and row[0] else None

    def list_open_sessions(self) -> list[dict[str, Any]]:
        """Return live sessions (those with an open episode), most-recently-seen first.

        Liveness is derived: a session is live iff it has an ``episodes`` row with
        ``ended_at IS NULL`` (at most one, by the open-episode invariant). Each row
        carries the session facets plus its live episode's ``source``/``started_at``.
        """

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT s.session_id, s.repo, s.worktree_label, s.handle, s.cwd,
                       s.transcript_path, s.created_at, s.last_seen_at,
                       e.source AS episode_source, e.started_at AS episode_started_at
                FROM sessions s
                JOIN episodes e
                    ON e.session_id = s.session_id AND e.ended_at IS NULL
                ORDER BY s.last_seen_at DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]
