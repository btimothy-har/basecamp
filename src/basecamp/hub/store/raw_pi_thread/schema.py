"""Schema for the ``raw_pi_thread`` head and ``raw_pi_thread_node`` tables."""

from __future__ import annotations

import sqlite3


class RawPiThreadSchemaMixin:
    """Create the ``raw_pi_thread`` + ``raw_pi_thread_node`` tables."""

    def _init_raw_pi_thread_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_pi_thread (
                owner_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                session_file TEXT,
                leaf_id TEXT,
                latest_seq INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_pi_thread_node (
                owner_id TEXT NOT NULL,
                entry_id TEXT NOT NULL,
                parent_id TEXT,
                first_seen_seq INTEGER NOT NULL,
                entry_json TEXT NOT NULL,
                PRIMARY KEY (owner_id, entry_id)
            )
            """
        )
