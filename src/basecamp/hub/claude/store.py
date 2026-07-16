"""Minimal SQLite store for Claude Code session liveness.

One table, ``sessions``, keyed by the native ``CLAUDE_CODE_SESSION_ID`` (or the
resolved node id of a daemon-spawned worker). Liveness is durable: a row is
*open* while ``ended_at IS NULL`` and *ended* once a SessionEnd hook stamps it.
Because that marker lives on disk, it survives daemon restarts — unlike an
in-memory connection registry, which the short-lived HTTP hooks could never keep
alive anyway.

This is deliberately independent of the legacy Pi ``agents`` table: the Claude
section owns its own database so it can be promoted (and the Pi side deleted)
without a shared-schema migration.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .paths import claude_sessions_db_path


class SessionStore:
    """Durable liveness for hook-registered Claude Code sessions."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path).expanduser() if db_path is not None else claude_sessions_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    role TEXT,
                    session_name TEXT,
                    cwd TEXT,
                    transcript_path TEXT,
                    repo TEXT,
                    worktree_label TEXT,
                    parent_id TEXT,
                    depth INTEGER,
                    created_at TEXT,
                    last_seen_at TEXT,
                    ended_at TEXT
                )
                """
            )

    def upsert_session(
        self,
        *,
        session_id: str,
        role: str,
        session_name: str,
        cwd: str,
        transcript_path: str | None = None,
        repo: str | None = None,
        worktree_label: str | None = None,
        parent_id: str | None = None,
        depth: int = 0,
    ) -> None:
        """Register (or re-open) a session, resetting ``ended_at`` to NULL.

        Re-registering the same id — a resume — reopens an ended row and refreshes
        its facets while preserving the original ``created_at``.
        """

        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (
                    session_id, role, session_name, cwd, transcript_path,
                    repo, worktree_label, parent_id, depth,
                    created_at, last_seen_at, ended_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(session_id) DO UPDATE SET
                    role = excluded.role,
                    session_name = excluded.session_name,
                    cwd = excluded.cwd,
                    transcript_path = excluded.transcript_path,
                    repo = excluded.repo,
                    worktree_label = excluded.worktree_label,
                    parent_id = excluded.parent_id,
                    depth = excluded.depth,
                    last_seen_at = excluded.last_seen_at,
                    ended_at = NULL
                """,
                (
                    session_id,
                    role,
                    session_name,
                    cwd,
                    transcript_path,
                    repo,
                    worktree_label,
                    parent_id,
                    depth,
                    now,
                    now,
                ),
            )

    def mark_session_ended(self, session_id: str) -> bool:
        """Stamp ``ended_at`` on a session; return whether a row was updated."""

        now = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE sessions SET ended_at = ?, last_seen_at = ? WHERE session_id = ?",
                (now, now, session_id),
            )
            return cursor.rowcount > 0

    def list_open_sessions(self) -> list[dict[str, Any]]:
        """Return open sessions (``ended_at IS NULL``), most-recently-seen first."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT session_id, role, depth, parent_id, session_name, cwd,
                       transcript_path, repo, worktree_label, created_at, last_seen_at
                FROM sessions
                WHERE ended_at IS NULL
                ORDER BY last_seen_at DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]
