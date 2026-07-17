"""The ``workstreams`` data object: a durable pointer record for staged work.

A workstream is a minimal coordination record — **pointers and identity, never
content**. It carries a stable id (``ws_<uuid>``) and a readable three-word
``slug``, a short ``label`` for listings, its ``status`` (``open``/``closed``),
the owning ``repo`` (canonical ``<org>/<name>``), and two pointers into content
that lives elsewhere: ``worktree_path`` (the permanent git worktree) and
``dossier_path`` (the shared-Logseq work page that holds the brief/decisions).

The brief is deliberately *not* stored here — the dossier is the brief, so a copy
in the record would drift. The branch is not stored either — cleanup reads it
from the worktree. This keeps the daemon a pure pointer index; everything
content-ish is in the dossier and everything git-ish is recoverable from the
worktree.

Schema follows the store's mixin idiom: ``CREATE TABLE IF NOT EXISTS`` with no
declared foreign keys (``repo``/paths are plain columns), so it initializes
order-independently on the shared connection alongside sessions/episodes.
"""

from __future__ import annotations

import sqlite3
from typing import Any

#: Allowed workstream statuses.
WORKSTREAM_STATUSES = ("open", "closed")


class WorkstreamsMixin:
    """Durable pointer records for copilot-staged workstreams."""

    def _init_workstreams_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workstreams (
                id TEXT PRIMARY KEY,
                slug TEXT UNIQUE NOT NULL,
                label TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                repo TEXT,
                worktree_path TEXT,
                dossier_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # Backs the by-worktree lookup that `basecamp workstream current` uses (C1c).
        connection.execute("CREATE INDEX IF NOT EXISTS idx_workstreams_worktree ON workstreams(worktree_path)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_workstreams_repo ON workstreams(repo)")

    def create_workstream(
        self,
        *,
        workstream_id: str,
        slug: str,
        label: str | None = None,
        repo: str | None = None,
        worktree_path: str | None = None,
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
                INSERT INTO workstreams (
                    id, slug, label, status, repo, worktree_path, dossier_path,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?)
                """,
                (workstream_id, slug, label, repo, worktree_path, dossier_path, now, now),
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

    def get_workstream_by_worktree(self, worktree_path: str) -> dict[str, Any] | None:
        """Return the workstream owning ``worktree_path``, or ``None``.

        Backs ``basecamp workstream current``: the path must be normalized
        identically at write and read (absolute, symlink-free) for the match to hit.
        """

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM workstreams WHERE worktree_path = ?",
                (worktree_path,),
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

    def delete_workstream(self, identifier: str) -> bool:
        """Delete a workstream record by id or slug; return whether a row was removed.

        Removes only the record — the worktree/branch/dossier teardown is the
        caller's (skill/tool) concern, never the store's.
        """

        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM workstreams WHERE id = ? OR slug = ?",
                (identifier, identifier),
            )
            return cursor.rowcount > 0
