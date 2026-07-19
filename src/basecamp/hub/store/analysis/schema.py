"""Schema for the ``analysis`` table (latest-only per session)."""

from __future__ import annotations

import sqlite3


class AnalysisSchemaMixin:
    """Create the ``analysis`` table."""

    def _init_analysis_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis (
                owner_id TEXT PRIMARY KEY,
                based_on_thread_seq INTEGER,
                model TEXT,
                sections_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
