"""Writes for the ``workstreams``, ``workstream_versions`` and ``workstream_agents`` tables."""

from __future__ import annotations

import sqlite3

from ..errors import DuplicateWorkstreamSlugError, WorkstreamNotFoundError
from .schema import WORKSTREAM_STATUSES


class WorkstreamsWriterMixin:
    """Workstream, workstream-version, and workstream-agent mutations."""

    @staticmethod
    def _insert_workstream_version(
        connection: sqlite3.Connection,
        *,
        workstream_id: str,
        version: int,
        label: str,
        brief: str,
        constraints: str | None,
        created_at: str,
    ) -> None:
        """Append one content snapshot to ``workstream_versions`` (append-only history)."""

        connection.execute(
            """
            INSERT INTO workstream_versions (workstream_id, version, label, brief, constraints, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (workstream_id, version, label, brief, constraints, created_at),
        )

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
        """Insert a new workstream row and seed its version-1 content snapshot."""

        timestamp = now or self._now()
        with self._writing() as connection:
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
                        version,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'open', 1, ?, ?)
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
            self._insert_workstream_version(
                connection,
                workstream_id=workstream_id,
                version=1,
                label=label,
                brief=brief,
                constraints=constraints,
                created_at=timestamp,
            )

    def revise_workstream(
        self,
        *,
        workstream_id: str,
        label: str,
        brief: str,
        constraints: str | None = None,
        now: str | None = None,
    ) -> int:
        """Revise a workstream's content in place, retaining the prior version.

        Bumps the version, snapshots the new content into ``workstream_versions``,
        and returns the new version number. Raises ``WorkstreamNotFoundError`` when
        the workstream is absent.
        """

        timestamp = now or self._now()
        with self._writing(immediate=True) as connection:
            row = connection.execute(
                "SELECT version FROM workstreams WHERE id = ?",
                (workstream_id,),
            ).fetchone()
            if row is None:
                raise WorkstreamNotFoundError(workstream_id)
            new_version = int(row[0]) + 1
            self._insert_workstream_version(
                connection,
                workstream_id=workstream_id,
                version=new_version,
                label=label,
                brief=brief,
                constraints=constraints,
                created_at=timestamp,
            )
            connection.execute(
                """
                UPDATE workstreams
                SET label = ?, brief = ?, constraints = ?, version = ?, updated_at = ?
                WHERE id = ?
                """,
                (label, brief, constraints, new_version, timestamp, workstream_id),
            )
            return new_version

    def set_workstream_status(self, *, workstream_id: str, status: str, now: str | None = None) -> bool:
        """Update a workstream's status; return whether a row was updated."""

        if status not in WORKSTREAM_STATUSES:
            raise ValueError("invalid workstream status")  # noqa: TRY003
        timestamp = now or self._now()
        with self._writing() as connection:
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
        with self._writing(immediate=True) as connection:
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
