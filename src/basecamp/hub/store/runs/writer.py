"""Writes for the ``runs`` and ``run_events`` tables."""

from __future__ import annotations

import json
from typing import Any

from ..errors import ActiveRunExistsError
from .schema import TERMINAL_STATUSES


class RunsWriterMixin:
    """Run lifecycle and run-event mutations."""

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
