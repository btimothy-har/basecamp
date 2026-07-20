"""Schema for the ``runs`` and ``run_events`` tables, plus run-status constants."""

from __future__ import annotations

import sqlite3

from .._sqlite import ensure_column

TERMINAL_STATUSES = ("completed", "failed")

# Columns added after the table's first release (the CREATE carries them fresh).
_RUNS_MIGRATED_COLUMNS = (
    ("dispatcher_id", "TEXT"),
    ("exit_code", "INTEGER"),
    ("pgid", "INTEGER"),
    ("report_token_hash", "TEXT"),
)


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
        for name, decl in _RUNS_MIGRATED_COLUMNS:
            ensure_column(connection, "runs", name, decl)
