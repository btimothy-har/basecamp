"""Schema for the ``runs`` and ``run_events`` tables, plus run-status constants."""

from __future__ import annotations

import sqlite3

TERMINAL_STATUSES = ("completed", "failed")


class RunsSchemaMixin:
    """Create the ``runs`` + ``run_events`` tables and migrate run columns."""

    def _init_runs_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                agent_id TEXT,
                status TEXT CHECK(status IN ('pending','running','completed','failed')),
                dispatcher_id TEXT,
                spec_json TEXT,
                report_token_hash TEXT,
                result TEXT,
                error TEXT,
                exit_code INTEGER,
                pgid INTEGER,
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
        self._ensure_runs_dispatcher_id_column(connection)
        self._ensure_runs_exit_code_column(connection)
        self._ensure_runs_pgid_column(connection)
        self._ensure_runs_report_token_hash_column(connection)

    def _ensure_runs_dispatcher_id_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(runs)").fetchall()
        names = {column[1] for column in columns}
        if "dispatcher_id" not in names:
            connection.execute("ALTER TABLE runs ADD COLUMN dispatcher_id TEXT")

    def _ensure_runs_exit_code_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(runs)").fetchall()
        names = {column[1] for column in columns}
        if "exit_code" not in names:
            connection.execute("ALTER TABLE runs ADD COLUMN exit_code INTEGER")

    def _ensure_runs_pgid_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(runs)").fetchall()
        names = {column[1] for column in columns}
        if "pgid" not in names:
            connection.execute("ALTER TABLE runs ADD COLUMN pgid INTEGER")

    def _ensure_runs_report_token_hash_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(runs)").fetchall()
        names = {column[1] for column in columns}
        if "report_token_hash" not in names:
            connection.execute("ALTER TABLE runs ADD COLUMN report_token_hash TEXT")
