"""Schema for the ``workstreams``, ``workstream_versions`` and ``workstream_agents`` tables."""

from __future__ import annotations

import sqlite3

from .._sqlite import ensure_column

WORKSTREAM_STATUSES = ("open", "closed")


class WorkstreamsSchemaMixin:
    """Create the workstream tables and migrate content-versioning columns in place."""

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
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workstream_versions (
                workstream_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                label TEXT NOT NULL,
                brief TEXT NOT NULL,
                constraints TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (workstream_id, version)
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
        ensure_column(connection, "workstreams", "version", "INTEGER NOT NULL DEFAULT 1")
        self._backfill_workstream_versions(connection)

    def _backfill_workstream_versions(self, connection: sqlite3.Connection) -> None:
        """Seed the history table with each workstream's current version snapshot.

        Idempotent: only inserts a row when the workstream's current (id, version)
        pair is absent, so pre-versioning rows gain a v1 snapshot exactly once and
        already-seeded lineages are untouched.
        """
        connection.execute(
            """
            INSERT INTO workstream_versions (workstream_id, version, label, brief, constraints, created_at)
            SELECT w.id, w.version, w.label, w.brief, w.constraints, w.created_at
            FROM workstreams AS w
            WHERE NOT EXISTS (
                SELECT 1 FROM workstream_versions AS v
                WHERE v.workstream_id = w.id AND v.version = w.version
            )
            """
        )
