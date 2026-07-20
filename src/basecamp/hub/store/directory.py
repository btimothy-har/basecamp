"""Agent directory and current-run projection mixin."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ._sqlite import load_json_column
from .text import _preview_text

# Soft-expiry TTL for the live agent roster: rows with no live connection and no
# activity within this window are dropped from list_agents (the row is retained).
AGENT_TTL_HOURS = 24


class DirectoryMixin:
    """Directory listings and current-run projections."""

    def get_root_agent_directory(
        self,
        *,
        requester_node_id: str,
        awaitable: bool = False,
        live_node_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """List non-session agents under the caller's root with safe status metadata.

        Soft expiry: rows whose agent has no live connection and has not been seen
        within AGENT_TTL_HOURS are dropped from the live roster.
        """

        root_id = self.resolve_agent_root(requester_node_id)
        if root_id is None:
            return []

        live = list(live_node_ids or ())
        cutoff = (datetime.now(UTC) - timedelta(hours=AGENT_TTL_HOURS)).isoformat()
        live_clause = f"a.id IN ({', '.join('?' for _ in live)})" if live else "0"
        awaitable_filter = "" if not awaitable else " AND r.id IS NOT NULL AND r.dispatcher_id = ? "
        query = f"""
            WITH RECURSIVE scoped_agents(id, parent_id, path) AS (
                SELECT id, parent_id, ',' || id || ','
                FROM agents
                WHERE id = ?
                UNION
                SELECT child.id,
                       child.parent_id,
                       path || child.id || ','
                FROM agents AS child
                INNER JOIN scoped_agents AS s ON child.parent_id = s.id
                WHERE instr(s.path, ',' || child.id || ',') = 0
            )
            SELECT
                a.id AS agent_id,
                a.agent_handle,
                a.agent_type,
                a.parent_id,
                a.role,
                a.session_name,
                a.depth,
                CASE
                    WHEN r.status IN ('pending', 'running', 'completed', 'failed') THEN r.status
                    ELSE 'idle'
                END AS status,
                CASE
                    WHEN r.id IS NOT NULL AND r.dispatcher_id = ? THEN 1
                    ELSE 0
                END AS awaitable,
                r.spec_json AS spec_json
            FROM scoped_agents AS s
            INNER JOIN agents AS a ON a.id = s.id
            LEFT JOIN runs AS r ON r.id = a.current_run_id
            WHERE a.role != 'agent'
              AND (a.agent_type IS NULL OR a.agent_type != 'ask')
              AND (a.last_seen_at >= ? OR {live_clause})
            {awaitable_filter}
            ORDER BY a.depth ASC, a.id ASC
            """

        params: list[Any] = [root_id, requester_node_id, cutoff, *live]
        if awaitable:
            params.append(requester_node_id)

        with self._reading() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()

        directory: list[dict[str, Any]] = []
        for row in rows:
            task: str | None = None
            spec = load_json_column(row["spec_json"])
            if isinstance(spec, dict):
                task = _preview_text(spec.get("task"))

            directory.append(
                {
                    "agent_id": row["agent_id"],
                    "agent_handle": row["agent_handle"],
                    "agent_type": row["agent_type"],
                    "parent_id": row["parent_id"],
                    "role": row["role"],
                    "session_name": row["session_name"],
                    "depth": row["depth"],
                    "status": row["status"],
                    "awaitable": bool(row["awaitable"]),
                    "task": task,
                }
            )
        return directory

    def get_agents_current_runs(
        self,
        agent_ids: list[str],
        *,
        dispatcher_id: str,
    ) -> list[dict[str, Any]]:
        """Return current primary-run projections for requested agents.

        Only runs owned by ``dispatcher_id`` are exposed. Missing agents,
        missing current runs, and unauthorized agents are returned without any
        run state in the row.
        """

        if not agent_ids:
            return []

        placeholders = ", ".join("?" for _ in agent_ids)
        query = f"""
            SELECT
                a.id AS agent_id,
                a.agent_handle,
                r.id AS run_id,
                r.status AS status,
                r.result AS result,
                r.error AS error
            FROM agents AS a
            LEFT JOIN runs AS r
                ON r.id = a.current_run_id
               AND r.dispatcher_id = ?
            WHERE a.id IN ({placeholders})
              AND a.role != 'agent'
            """

        with self._reading() as connection:
            rows = connection.execute(query, (dispatcher_id, *agent_ids)).fetchall()

        return [dict(row) for row in rows]

    def get_agents_current_runs_by_handles(
        self,
        agent_handles: list[str],
        *,
        dispatcher_id: str,
    ) -> list[dict[str, Any]]:
        """Return current primary-run projections for requested agent handles."""

        if not agent_handles:
            return []

        placeholders = ", ".join("?" for _ in agent_handles)
        query = f"""
            SELECT
                a.id AS agent_id,
                a.agent_handle,
                r.id AS run_id,
                r.status AS status,
                r.result AS result,
                r.error AS error
            FROM agents AS a
            LEFT JOIN runs AS r
                ON r.id = a.current_run_id
               AND r.dispatcher_id = ?
            WHERE a.agent_handle IN ({placeholders})
              AND a.role != 'agent'
            """

        with self._reading() as connection:
            rows = connection.execute(query, (dispatcher_id, *agent_handles)).fetchall()

        return [dict(row) for row in rows]
