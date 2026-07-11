"""Schema for the ``workstreams`` and ``workstream_agents`` tables."""

from __future__ import annotations

import sqlite3

WORKSTREAM_STATUSES = ("open", "closed")


class WorkstreamsSchemaMixin:
    """Create the ``workstreams`` + ``workstream_agents`` tables."""

    def _init_workstreams_schema(self, connection: sqlite3.Connection) -> None:
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
