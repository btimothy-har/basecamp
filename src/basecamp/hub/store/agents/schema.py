"""Schema for the ``agents`` table: DDL plus ALTER-based column migrations."""

from __future__ import annotations

import sqlite3

from .._sqlite import ensure_column
from ..text import _fallback_agent_handle

# Columns added after the table's first release; each is ensured in place on an
# older db (the CREATE below carries them for a fresh one).
_AGENTS_MIGRATED_COLUMNS = (
    ("current_run_id", "TEXT"),
    ("agent_type", "TEXT"),
    ("model", "TEXT"),
    ("session_file", "TEXT"),
    ("repo", "TEXT"),
    ("worktree_label", "TEXT"),
    ("branch", "TEXT"),
    ("agent_mode", "TEXT"),
)


class AgentsSchemaMixin:
    """Create the ``agents`` table and migrate its columns in place."""

    def _init_agents_schema(self, connection: sqlite3.Connection) -> None:
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
                last_seen_at TEXT,
                current_run_id TEXT,
                agent_handle TEXT,
                agent_type TEXT,
                model TEXT,
                session_file TEXT,
                repo TEXT,
                worktree_label TEXT,
                branch TEXT,
                agent_mode TEXT
            )
            """
        )
        for name, decl in _AGENTS_MIGRATED_COLUMNS:
            ensure_column(connection, "agents", name, decl)
        self._ensure_agents_agent_handle(connection)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_agents_parent_id ON agents(parent_id)")
        self._migrate_agents_role_values(connection)
        self._drop_agents_retired_columns(connection)

    def _ensure_agents_agent_handle(self, connection: sqlite3.Connection) -> None:
        """Add ``agent_handle``, backfill legacy rows from the id, and index it uniquely."""
        ensure_column(connection, "agents", "agent_handle", "TEXT")

        rows = connection.execute("SELECT id FROM agents WHERE agent_handle IS NULL OR agent_handle = ''").fetchall()
        for row in rows:
            agent_id = row[0]
            connection.execute(
                "UPDATE agents SET agent_handle = ? WHERE id = ?",
                (_fallback_agent_handle(agent_id), agent_id),
            )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_agent_handle_unique
            ON agents(agent_handle)
            WHERE agent_handle IS NOT NULL
            """
        )

    def _drop_agents_retired_columns(self, connection: sqlite3.Connection) -> None:
        """Drop retired columns: product_role (agent-role seam), run_kind (mutative guards).

        ``ALTER TABLE ... DROP COLUMN`` needs SQLite 3.35+. On older engines we skip
        the drops: both columns are inert (no reader or writer references them), so
        retaining them is harmless and never worth crash-looping daemon start over.
        """
        if sqlite3.sqlite_version_info < (3, 35, 0):
            return
        columns = connection.execute("PRAGMA table_info(agents)").fetchall()
        names = {column[1] for column in columns}
        if "product_role" in names:
            connection.execute("ALTER TABLE agents DROP COLUMN product_role")
        if "run_kind" in names:
            connection.execute("ALTER TABLE agents DROP COLUMN run_kind")

    def _migrate_agents_role_values(self, connection: sqlite3.Connection) -> None:
        """One-shot remap of legacy node-kind values: session->agent, agent->worker."""
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version >= 1:
            return
        connection.execute(
            "UPDATE agents SET role = CASE role WHEN 'session' THEN 'agent' WHEN 'agent' THEN 'worker' ELSE role END"
        )
        connection.execute("PRAGMA user_version = 1")
