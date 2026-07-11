"""Writes for the ``workstreams`` and ``workstream_agents`` tables."""

from __future__ import annotations

import sqlite3

from ..errors import DuplicateWorkstreamSlugError, WorkstreamNotFoundError
from .schema import WORKSTREAM_STATUSES


class WorkstreamsWriterMixin:
    """Workstream and workstream-agent mutations."""

    def create_workstream(
        self,
        *,
        workstream_id: str,
        slug: str,
        label: str,
        brief: str,
        source_dossier_path: str,
        constraints: str | None = None,
        source_repo_page_path: str | None = None,
        now: str | None = None,
    ) -> None:
        """Insert a new workstream row."""

        timestamp = now or self._now()
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO workstreams (
                        id,
                        slug,
                        label,
                        brief,
                        constraints,
                        source_dossier_path,
                        source_repo_page_path,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
                    """,
                    (
                        workstream_id,
                        slug,
                        label,
                        brief,
                        constraints,
                        source_dossier_path,
                        source_repo_page_path,
                        timestamp,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as error:
                if "workstreams.slug" in str(error):
                    raise DuplicateWorkstreamSlugError(slug) from error
                raise

    def set_workstream_status(self, *, workstream_id: str, status: str, now: str | None = None) -> bool:
        """Update a workstream's status; return whether a row was updated."""

        if status not in WORKSTREAM_STATUSES:
            raise ValueError("invalid workstream status")  # noqa: TRY003
        timestamp = now or self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE workstreams SET status = ?, updated_at = ? WHERE id = ?",
                (status, timestamp, workstream_id),
            )
            return cursor.rowcount > 0

    def attach_workstream_agent(
        self,
        *,
        workstream_id: str,
        agent_id: str,
        repo: str | None = None,
        worktree_label: str | None = None,
        status: str = "attached",
        error: str | None = None,
        now: str | None = None,
    ) -> None:
        """Attach (or re-attach) an agent to a workstream."""

        timestamp = now or self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT id FROM workstreams WHERE id = ?",
                (workstream_id,),
            ).fetchone()
            if existing is None:
                raise WorkstreamNotFoundError(workstream_id)
            connection.execute(
                """
                INSERT INTO workstream_agents (
                    workstream_id,
                    agent_id,
                    repo,
                    worktree_label,
                    status,
                    error,
                    joined_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workstream_id, agent_id)
                DO UPDATE SET
                    repo = excluded.repo,
                    worktree_label = excluded.worktree_label,
                    status = excluded.status,
                    error = excluded.error
                """,
                (
                    workstream_id,
                    agent_id,
                    repo,
                    worktree_label,
                    status,
                    error,
                    timestamp,
                ),
            )
