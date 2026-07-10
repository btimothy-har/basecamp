"""Schema initialization and column migrations for the daemon store database."""

from __future__ import annotations

import sqlite3

from .text import _fallback_agent_handle


class SchemaMixin:
    """Database schema creation and ALTER-based column migrations."""

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
                    last_seen_at TEXT,
                    current_run_id TEXT,
                    agent_handle TEXT,
                    agent_type TEXT,
                    run_kind TEXT,
                    model TEXT,
                    session_file TEXT,
                    product_role TEXT
                )
                """
            )
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    root_id TEXT,
                    sender_node_id TEXT,
                    sender_handle TEXT,
                    target_agent_id TEXT,
                    target_handle TEXT,
                    content TEXT,
                    interrupt INTEGER,
                    status TEXT CHECK(status IN ('accepted','sent','queued','failed','unavailable')),
                    error TEXT,
                    created_at TEXT,
                    sent_at TEXT,
                    queued_at TEXT,
                    failed_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workstreams (
                    id TEXT PRIMARY KEY,
                    slug TEXT UNIQUE NOT NULL,
                    label TEXT NOT NULL,
                    brief TEXT NOT NULL,
                    constraints TEXT,
                    source_dossier_path TEXT NOT NULL,
                    source_repo_page_path TEXT,
                    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workstream_agents (
                    workstream_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    repo TEXT,
                    worktree_label TEXT,
                    status TEXT,
                    error TEXT,
                    joined_at TEXT NOT NULL,
                    PRIMARY KEY (workstream_id, agent_id)
                )
                """
            )
            self._ensure_agents_current_run_id_column(connection)
            self._ensure_agents_agent_handle_column(connection)
            self._ensure_agents_metadata_columns(connection)
            self._ensure_agents_model_column(connection)
            self._ensure_agents_session_file_column(connection)
            self._ensure_agents_product_role_column(connection)
            self._ensure_runs_dispatcher_id_column(connection)
            self._ensure_runs_exit_code_column(connection)
            self._ensure_runs_pgid_column(connection)
            self._ensure_runs_report_token_hash_column(connection)

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
        if "run_kind" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN run_kind TEXT")

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

    def _ensure_agents_product_role_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(agents)").fetchall()
        names = {column[1] for column in columns}
        if "product_role" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN product_role TEXT")

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
