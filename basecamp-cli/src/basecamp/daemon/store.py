"""SQLite-backed persistence for daemon agents and runs."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("~/.pi/agent/basecamp/daemon.db").expanduser()


TERMINAL_STATUSES = ("completed", "failed")


class Store:
    """Daemon persistence layer backed by SQLite."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path).expanduser() if db_path is not None else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    parent_id TEXT,
                    sibling_group TEXT,
                    depth INTEGER,
                    role TEXT,
                    session_name TEXT,
                    cwd TEXT,
                    created_at TEXT,
                    last_seen_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT,
                    status TEXT CHECK(status IN ('pending','running','completed','failed')),
                    spec_json TEXT,
                    result TEXT,
                    error TEXT,
                    exit_code INTEGER,
                    created_at TEXT,
                    started_at TEXT,
                    ended_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS run_events (
                    run_id TEXT,
                    seq INTEGER,
                    kind TEXT,
                    payload_json TEXT,
                    ts TEXT,
                    PRIMARY KEY (run_id, seq)
                )
                """
            )
            self._ensure_runs_exit_code_column(connection)

    def _ensure_runs_exit_code_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(runs)").fetchall()
        names = {column[1] for column in columns}
        if "exit_code" not in names:
            connection.execute("ALTER TABLE runs ADD COLUMN exit_code INTEGER")

    def upsert_agent(
        self,
        *,
        agent_id: str,
        parent_id: str | None,
        sibling_group: str | None,
        depth: int,
        role: str,
        session_name: str,
        cwd: str,
    ) -> None:
        """Insert/update an agent row and refresh last-seen timestamp."""

        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agents (
                    id,
                    parent_id,
                    sibling_group,
                    depth,
                    role,
                    session_name,
                    cwd,
                    created_at,
                    last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id)
                DO UPDATE SET
                    parent_id = excluded.parent_id,
                    sibling_group = excluded.sibling_group,
                    depth = excluded.depth,
                    role = excluded.role,
                    session_name = excluded.session_name,
                    cwd = excluded.cwd,
                    last_seen_at = excluded.last_seen_at
                """,
                (agent_id, parent_id, sibling_group, depth, role, session_name, cwd, now, now),
            )

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Fetch an agent by id as a dict, or None when absent."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            return dict(row) if row is not None else None

    def create_run(self, *, run_id: str, agent_id: str, spec: dict[str, Any]) -> None:
        """Create a running run row."""

        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (id, agent_id, status, spec_json, created_at, started_at)
                VALUES (?, ?, 'running', ?, ?, ?)
                """,
                (run_id, agent_id, json.dumps(spec), now, now),
            )

    def set_run_exit_code(self, *, run_id: str, exit_code: int | None) -> None:
        """Persist subprocess exit code for a run."""

        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET exit_code = ? WHERE id = ?",
                (exit_code, run_id),
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
            connection.execute(
                """
                UPDATE runs
                SET status = ?, result = ?, error = ?, ended_at = ?
                WHERE id = ?
                """,
                (status, result, error, ended_at, run_id),
            )

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
            return cursor.rowcount > 0

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

    def are_runs_terminal(self, run_ids: list[str]) -> bool:
        """Return True when all requested run ids exist and are terminal."""

        if not run_ids:
            return True

        placeholders = ", ".join("?" for _ in run_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id, status FROM runs WHERE id IN ({placeholders})",
                tuple(run_ids),
            ).fetchall()

        by_id = {row[0]: row[1] for row in rows}
        if len(by_id) != len(run_ids):
            return False
        return all(by_id[run_id] in TERMINAL_STATUSES for run_id in run_ids)

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
