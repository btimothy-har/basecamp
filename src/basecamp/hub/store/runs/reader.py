"""Reads for the ``runs`` and ``run_events`` tables."""

from __future__ import annotations

from typing import Any

from .._sqlite import load_json_column
from .schema import TERMINAL_STATUSES


class RunsReaderMixin:
    """Run and run-event queries."""

    def get_nonterminal_runs(self) -> list[dict[str, Any]]:
        """Return runs that are not in a terminal status.

        Includes the parsed ``spec_json`` so restart reconciliation can tear down a mutative
        agent's workspace (the reaper's counterpart after a daemon crash).
        """

        with self._reading() as connection:
            rows = connection.execute(
                """
                SELECT id, agent_id, pgid, status, spec_json
                FROM runs
                WHERE status NOT IN (?, ?)
                """,
                TERMINAL_STATUSES,
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            result = dict(row)
            result["spec_json"] = load_json_column(result.get("spec_json"))
            results.append(result)
        return results

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Fetch a run by id as a dict, or None when absent."""

        with self._reading() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["spec_json"] = load_json_column(result.get("spec_json"))
            return result

    def resolve_agent_root(self, agent_id: str) -> str | None:
        """Resolve the root id for an agent by following parent links defensively."""

        visited: set[str] = set()
        current = agent_id

        while isinstance(current, str) and current not in visited:
            visited.add(current)
            row = self.get_agent(current)
            if row is None:
                return None

            parent_id = row.get("parent_id")
            if not isinstance(parent_id, str) or not parent_id.strip():
                return current
            if self.get_agent(parent_id) is None:
                return current
            current = parent_id

        return current if isinstance(current, str) else None

    def get_run_wait_results(self, run_ids: list[str], *, terminal_only: bool = False) -> list[dict[str, Any]]:
        """Return wait result projections for requested run ids.

        When ``terminal_only`` is true, returns only completed/failed runs.
        """

        if not run_ids:
            return []

        placeholders = ", ".join("?" for _ in run_ids)
        where_terminal = " AND status IN ('completed', 'failed')" if terminal_only else ""
        query = f"SELECT id, status, result, error FROM runs WHERE id IN ({placeholders}){where_terminal}"

        with self._reading() as connection:
            rows = connection.execute(query, tuple(run_ids)).fetchall()

        return [
            {
                "run_id": row["id"],
                "status": row["status"],
                "result": row["result"],
                "error": row["error"],
            }
            for row in rows
        ]

    def get_run_events(self, run_id: str) -> list[dict[str, Any]]:
        """Return run events in sequence order."""

        with self._reading() as connection:
            rows = connection.execute(
                "SELECT run_id, seq, kind, payload_json, ts FROM run_events WHERE run_id = ? ORDER BY seq ASC",
                (run_id,),
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["payload_json"] = load_json_column(data.get("payload_json"))
            results.append(data)
        return results
