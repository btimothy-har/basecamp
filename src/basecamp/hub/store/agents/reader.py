"""Reads for the ``agents`` table."""

from __future__ import annotations

import sqlite3
from typing import Any


class AgentsReaderMixin:
    """Agent registry queries."""

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Fetch an agent by id as a dict, or None when absent."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            return dict(row) if row is not None else None

    def get_agent_by_handle(self, agent_handle: str) -> dict[str, Any] | None:
        """Fetch an agent by public handle as a dict, or None when absent."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM agents WHERE agent_handle = ?", (agent_handle,)).fetchone()
            return dict(row) if row is not None else None

    def list_open_sessions(self) -> list[dict[str, Any]]:
        """Return registered sessions that are still open (``ended_at IS NULL``).

        Ordered most-recently-seen first. This is the durable, restart-surviving
        view of live sessions the hook-driven lifecycle registers.
        """

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT id, role, depth, parent_id, session_name, cwd,
                       session_file, repo, worktree_label, created_at, last_seen_at
                FROM agents
                WHERE ended_at IS NULL
                ORDER BY last_seen_at DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_subtree_agent_ids(self, root_agent_id: str) -> list[str]:
        """Return root agent id and all transitive descendant agent ids."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH RECURSIVE subtree(id) AS (
                    SELECT id FROM agents WHERE id = ?
                    UNION
                    SELECT a.id FROM agents a JOIN subtree s ON a.parent_id = s.id
                )
                SELECT id FROM subtree
                """,
                (root_agent_id,),
            ).fetchall()
            return [row[0] for row in rows]
