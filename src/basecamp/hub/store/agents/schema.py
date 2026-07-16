"""Schema for the ``agents`` table: DDL plus ALTER-based column migrations."""

from __future__ import annotations

import sqlite3

from ..text import _fallback_agent_handle


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
                ended_at TEXT
            )
            """
        )
        self._ensure_agents_current_run_id_column(connection)
        self._ensure_agents_agent_handle_column(connection)
        self._ensure_agents_metadata_columns(connection)
        self._ensure_agents_model_column(connection)
        self._ensure_agents_session_file_column(connection)
        self._ensure_agents_facet_columns(connection)
        self._ensure_agents_ended_at_column(connection)
        self._migrate_agents_role_values(connection)
        self._drop_agents_retired_columns(connection)

    def _ensure_agents_current_run_id_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(agents)").fetchall()
        names = {column[1] for column in columns}
        if "current_run_id" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN current_run_id TEXT")

    def _ensure_agents_agent_handle_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(agents)").fetchall()
        names = {column[1] for column in columns}
        if "agent_handle" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN agent_handle TEXT")

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

    def _ensure_agents_metadata_columns(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(agents)").fetchall()
        names = {column[1] for column in columns}
        if "agent_type" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN agent_type TEXT")

    def _ensure_agents_model_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(agents)").fetchall()
        names = {column[1] for column in columns}
        if "model" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN model TEXT")

    def _ensure_agents_session_file_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(agents)").fetchall()
        names = {column[1] for column in columns}
        if "session_file" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN session_file TEXT")

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

    def _ensure_agents_facet_columns(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(agents)").fetchall()
        names = {column[1] for column in columns}
        if "repo" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN repo TEXT")
        if "worktree_label" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN worktree_label TEXT")

    def _ensure_agents_ended_at_column(self, connection: sqlite3.Connection) -> None:
        # ended_at is the durable session-liveness marker (NULL = open/live). It
        # survives daemon restarts, unlike the in-memory WebSocket registry, which
        # is what the hook-driven Claude Code session lifecycle relies on.
        columns = connection.execute("PRAGMA table_info(agents)").fetchall()
        names = {column[1] for column in columns}
        if "ended_at" in names:
            return
        connection.execute("ALTER TABLE agents ADD COLUMN ended_at TEXT")
        # Rows that predate this column predate the hook-driven session lifecycle,
        # so none of them is a live hook session. Backfill them as already-ended so
        # list_open_sessions (open == ended_at IS NULL) never reports stale
        # pre-migration rows as live. A genuine resume re-registers, and
        # upsert_agent resets ended_at to NULL. Runs only on the one migration that
        # first adds the column (daemon start, before any connection), so it never
        # clobbers a live session.
        connection.execute(
            "UPDATE agents SET ended_at = COALESCE(last_seen_at, created_at, ?)",
            (self._now(),),
        )

    def _migrate_agents_role_values(self, connection: sqlite3.Connection) -> None:
        """One-shot remap of legacy node-kind values: session->agent, agent->worker."""
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version >= 1:
            return
        connection.execute(
            "UPDATE agents SET role = CASE role WHEN 'session' THEN 'agent' WHEN 'agent' THEN 'worker' ELSE role END"
        )
        connection.execute("PRAGMA user_version = 1")
