"""The ``workstreams`` data object: the hub's durable handle for a unit of work.

A workstream is the hub's own durable coordination record — the anchor, because
the dossier it maps to lives *outside* the hub (a ``.md`` in the shared Logseq
graph). It carries a stable id (``ws_<uuid>``) and a readable ``slug``, a short
``label``, its ``status``, the ``repo`` it was created in, and a ``dossier_path``
pointing at that external work page. One workstream ↔ one dossier.

**Agents attach to the workstream, not to a worktree.** Many sessions can work a
workstream over time or at once, each from its own repo/worktree — so portability
and multi-worker both fall out of the attach rows, and the record stores no single
worktree path. Liveness is derived: an attached session with an open ``episodes``
row is live (the prune signal).

Schema follows the store's mixin idiom: ``CREATE TABLE IF NOT EXISTS`` with no
declared foreign keys (``session_id``/``workstream_id`` are logical refs), so it
initializes order-independently alongside sessions/episodes.
"""

from __future__ import annotations

import sqlite3
from typing import Any

#: Allowed workstream statuses.
WORKSTREAM_STATUSES = ("open", "closed")


class WorkstreamsMixin:
    """Durable workstream records plus the agent-attachment rows that link sessions to them."""

    def _init_workstreams_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workstreams (
                id TEXT PRIMARY KEY,
                slug TEXT UNIQUE NOT NULL,
                label TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                repo TEXT,
                dossier_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_workstreams_repo ON workstreams(repo)")
        # Agent attachment: many sessions per workstream, each carrying its own
        # repo/worktree (portability + multi-worker). Additive/idempotent by
        # (workstream_id, session_id).
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workstream_sessions (
                workstream_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                repo TEXT,
                worktree_path TEXT,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (workstream_id, session_id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_workstream_sessions_ws ON workstream_sessions(workstream_id)"
        )

    def create_workstream(
        self,
        *,
        workstream_id: str,
        slug: str,
        label: str | None = None,
        repo: str | None = None,
        dossier_path: str | None = None,
    ) -> dict[str, Any]:
        """Insert a new workstream record and return it.

        The caller (the MCP tool) mints ``workstream_id`` and ``slug``; a plain INSERT
        surfaces a slug collision as :class:`sqlite3.IntegrityError` on the UNIQUE
        constraint, which the route maps to 409 so the tool retries a fresh slug.
        """

        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workstreams (id, slug, label, status, repo, dossier_path, created_at, updated_at)
                VALUES (?, ?, ?, 'open', ?, ?, ?, ?)
                """,
                (workstream_id, slug, label, repo, dossier_path, now, now),
            )
        return self.get_workstream(workstream_id) or {}

    def get_workstream(self, identifier: str) -> dict[str, Any] | None:
        """Return a workstream by id **or** slug, or ``None`` if absent."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM workstreams WHERE id = ? OR slug = ?",
                (identifier, identifier),
            ).fetchone()
        return dict(row) if row else None

    def list_workstreams(
        self,
        *,
        repo: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List workstreams (optionally filtered by repo and/or status), newest first."""

        clauses: list[str] = []
        params: list[Any] = []
        if repo is not None:
            clauses.append("repo = ?")
            params.append(repo)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"SELECT * FROM workstreams {where} ORDER BY updated_at DESC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def set_workstream_status(self, identifier: str, status: str) -> bool:
        """Set a workstream's status (``open``/``closed``); return whether a row changed.

        Raises :class:`ValueError` for an unknown status so the route can reply 400
        rather than persisting an invalid value.
        """

        if status not in WORKSTREAM_STATUSES:
            msg = f"invalid status: {status!r}"
            raise ValueError(msg)
        now = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE workstreams SET status = ?, updated_at = ? WHERE id = ? OR slug = ?",
                (status, now, identifier, identifier),
            )
            return cursor.rowcount > 0

    def attach_workstream_session(
        self,
        *,
        identifier: str,
        session_id: str,
        repo: str | None = None,
        worktree_path: str | None = None,
    ) -> bool:
        """Attach a session (agent) to a workstream; ``False`` if the workstream is unknown.

        Additive and idempotent: re-attaching the same ``session_id`` refreshes its
        ``repo``/``worktree_path`` (preserving ``joined_at``) rather than duplicating.
        Resolves ``identifier`` (id or slug) to the workstream id so a slug attaches too.
        """

        workstream = self.get_workstream(identifier)
        if workstream is None:
            return False
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workstream_sessions (workstream_id, session_id, repo, worktree_path, joined_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workstream_id, session_id) DO UPDATE SET
                    repo = excluded.repo,
                    worktree_path = excluded.worktree_path
                """,
                (workstream["id"], session_id, repo, worktree_path, now),
            )
        return True

    def list_workstream_sessions(self, identifier: str) -> list[dict[str, Any]]:
        """Return the sessions attached to a workstream, each with its live/ended flag.

        Liveness is derived from ``episodes`` (an open episode ⇒ live), so this doubles
        as the prune signal: a workstream whose attached sessions are all ended has no
        live worker.
        """

        workstream = self.get_workstream(identifier)
        if workstream is None:
            return []
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT ws.session_id, ws.repo, ws.worktree_path, ws.joined_at,
                       EXISTS(
                           SELECT 1 FROM episodes e
                           WHERE e.session_id = ws.session_id AND e.ended_at IS NULL
                       ) AS live
                FROM workstream_sessions ws
                WHERE ws.workstream_id = ?
                ORDER BY ws.joined_at ASC
                """,
                (workstream["id"],),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_workstream(self, identifier: str) -> bool:
        """Delete a workstream record (and its attach rows) by id or slug.

        Removes only hub state — the worktree/branch/dossier teardown is the caller's
        (skill/tool) concern, never the store's. Attach rows are removed explicitly
        since there are no SQL cascades.
        """

        workstream = self.get_workstream(identifier)
        if workstream is None:
            return False
        with self._connect() as connection:
            connection.execute("DELETE FROM workstream_sessions WHERE workstream_id = ?", (workstream["id"],))
            cursor = connection.execute("DELETE FROM workstreams WHERE id = ?", (workstream["id"],))
            return cursor.rowcount > 0
