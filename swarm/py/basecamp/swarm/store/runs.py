"""Run lifecycle persistence mixin."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .errors import ActiveRunExistsError

TERMINAL_STATUSES = ("completed", "failed")


class RunsMixin:
    """Run lifecycle, run-event, and wait-result operations."""

    def create_run(
        self,
        *,
        run_id: str,
        agent_id: str,
        dispatcher_id: str,
        spec: dict[str, Any],
        report_token_hash: str | None = None,
    ) -> None:
        """Create a running run row."""

        now = self._now()
        with self._connect() as connection:
            existing_active = connection.execute(
                """
                SELECT id
                FROM runs
                WHERE agent_id = ?
                  AND status NOT IN (?, ?)
                LIMIT 1
                """,
                (agent_id, *TERMINAL_STATUSES),
            ).fetchone()
            if existing_active is not None:
                raise ActiveRunExistsError(agent_id)

            connection.execute(
                """
                INSERT INTO runs (
                    id,
                    agent_id,
                    status,
                    dispatcher_id,
                    spec_json,
                    report_token_hash,
                    created_at,
                    started_at
                )
                VALUES (?, ?, 'running', ?, ?, ?, ?, ?)
                """,
                (run_id, agent_id, dispatcher_id, json.dumps(spec), report_token_hash, now, now),
            )
            connection.execute(
                "UPDATE agents SET current_run_id = ? WHERE id = ?",
                (run_id, agent_id),
            )

    def set_run_exit_code(self, *, run_id: str, exit_code: int | None) -> None:
        """Persist subprocess exit code for a run."""

        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET exit_code = ? WHERE id = ?",
                (exit_code, run_id),
            )

    def set_run_pgid(self, *, run_id: str, pgid: int | None) -> None:
        """Persist subprocess process-group id for a run."""

        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET pgid = ? WHERE id = ?",
                (pgid, run_id),
            )

    def get_nonterminal_runs(self) -> list[dict[str, Any]]:
        """Return runs that are not in a terminal status."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT id, agent_id, pgid, status
                FROM runs
                WHERE status NOT IN (?, ?)
                """,
                TERMINAL_STATUSES,
            ).fetchall()

        return [dict(row) for row in rows]

    def set_run_result(
        self,
        *,
        run_id: str,
        status: str,
        result: str | None,
        error: str | None,
    ) -> None:
        """Persist terminal result/error state for a run."""

        ended_at = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET status = ?, result = ?, error = ?, ended_at = ?
                WHERE id = ?
                """,
                (status, result, error, ended_at, run_id),
            )
            if cursor.rowcount == 0:
                return

    def set_run_result_if_unset(
        self,
        *,
        run_id: str,
        status: str,
        result: str | None,
        error: str | None,
    ) -> bool:
        """Set terminal run result using first-writer-wins semantics."""

        ended_at = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET status = ?, result = ?, error = ?, ended_at = ?
                WHERE id = ?
                  AND status IN ('pending', 'running')
                """,
                (status, result, error, ended_at, run_id),
            )
            if cursor.rowcount == 0:
                return False

            return True

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Fetch a run by id as a dict, or None when absent."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            spec_json = result.get("spec_json")
            if isinstance(spec_json, str):
                result["spec_json"] = json.loads(spec_json)
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

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
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

    def append_run_event(self, *, run_id: str, kind: str, payload: dict[str, Any]) -> int:
        """Append an ordered event row for a run and return its sequence number."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            next_seq = connection.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM run_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO run_events (run_id, seq, kind, payload_json, ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, int(next_seq), kind, json.dumps(payload), self._now()),
            )
            return int(next_seq)

    def get_run_events(self, run_id: str) -> list[dict[str, Any]]:
        """Return run events in sequence order."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT run_id, seq, kind, payload_json, ts FROM run_events WHERE run_id = ? ORDER BY seq ASC",
                (run_id,),
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            payload_json = data.get("payload_json")
            if isinstance(payload_json, str):
                data["payload_json"] = json.loads(payload_json)
            results.append(data)
        return results
