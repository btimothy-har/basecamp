"""SQLite-backed persistence for daemon agents and runs."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("~/.pi/agent/basecamp/daemon.db").expanduser()


class Store:
    """Daemon persistence layer backed by SQLite."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path).expanduser() if db_path is not None else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

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
                    created_at TEXT,
                    started_at TEXT,
                    ended_at TEXT
                )
                """
            )

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

        now = datetime.now(UTC).isoformat()
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

    def create_run(self, *, run_id: str, agent_id: str, spec: dict[str, Any]) -> None:
        """Create a pending run row."""

        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (id, agent_id, status, spec_json, created_at)
                VALUES (?, ?, 'pending', ?, ?)
                """,
                (run_id, agent_id, json.dumps(spec), now),
            )

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
