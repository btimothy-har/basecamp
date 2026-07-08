"""Workstream persistence mixin."""

from __future__ import annotations

import sqlite3
from typing import Any

from .errors import DuplicateWorkstreamSlugError, WorkstreamNotFoundError

WORKSTREAM_STATUSES = ("open", "closed")


class WorkstreamsMixin:
    """Workstream and workstream-agent operations."""

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

    def get_workstream(self, identifier: str) -> dict[str, Any] | None:
        """Fetch a workstream by id or slug as a dict, or None when absent."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM workstreams WHERE id = ? OR slug = ?",
                (identifier, identifier),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_workstream_with_agents(self, identifier: str) -> dict[str, Any] | None:
        """Fetch a workstream by id or slug with its attached agents."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            ws_row = connection.execute(
                "SELECT * FROM workstreams WHERE id = ? OR slug = ?",
                (identifier, identifier),
            ).fetchone()
            if ws_row is None:
                return None

            agent_rows = connection.execute(
                """
                SELECT
                    wa.agent_id AS agent_id,
                    a.agent_handle AS agent_handle,
                    wa.repo AS repo,
                    wa.worktree_label AS worktree_label,
                    wa.status AS status,
                    wa.error AS error,
                    wa.joined_at AS joined_at,
                    r.status AS run_status
                FROM workstream_agents AS wa
                INNER JOIN agents AS a ON a.id = wa.agent_id
                LEFT JOIN runs AS r ON r.id = a.current_run_id
                WHERE wa.workstream_id = ?
                ORDER BY wa.joined_at ASC
                """,
                (ws_row["id"],),
            ).fetchall()

        result = dict(ws_row)
        result["agents"] = [
            {
                "agent_id": row["agent_id"],
                "agent_handle": row["agent_handle"],
                "repo": row["repo"],
                "worktree_label": row["worktree_label"],
                "status": row["status"],
                "error": row["error"],
                "joined_at": row["joined_at"],
                "run_status": row["run_status"],
            }
            for row in agent_rows
        ]
        return result

    def list_workstreams(
        self,
        *,
        status: str | None = None,
        repo: str | None = None,
        dossier_path: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """List workstreams with optional filters, ordered by updated_at DESC."""

        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("w.status = ?")
            params.append(status)
        if dossier_path is not None:
            clauses.append("w.source_dossier_path = ?")
            params.append(dossier_path)
        if query is not None:
            clauses.append("(LOWER(w.slug) LIKE LOWER(?) OR LOWER(w.label) LIKE LOWER(?))")
            like = f"%{query}%"
            params.extend([like, like])
        if repo is not None:
            clauses.append("EXISTS (SELECT 1 FROM workstream_agents wa WHERE wa.workstream_id = w.id AND wa.repo = ?)")
            params.append(repo)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT
                w.*,
                (SELECT COUNT(*) FROM workstream_agents wa WHERE wa.workstream_id = w.id) AS agent_count
            FROM workstreams AS w
            {where}
            ORDER BY w.updated_at DESC
        """

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(sql, tuple(params)).fetchall()

        return [dict(row) for row in rows]

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
