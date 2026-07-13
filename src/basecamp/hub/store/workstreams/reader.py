"""Reads for the ``workstreams`` and ``workstream_agents`` tables."""

from __future__ import annotations

import sqlite3
from typing import Any


class WorkstreamsReaderMixin:
    """Workstream and workstream-agent queries."""

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
        """Fetch a workstream by id or slug with its attached agents and version history."""

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
            version_rows = self._read_workstream_versions(connection, ws_row["id"])

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
        result["versions"] = version_rows
        return result

    def list_workstream_versions(self, identifier: str) -> list[dict[str, Any]] | None:
        """List a workstream's content-version history (newest first), or None when absent."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            ws_row = connection.execute(
                "SELECT id FROM workstreams WHERE id = ? OR slug = ?",
                (identifier, identifier),
            ).fetchone()
            if ws_row is None:
                return None
            return self._read_workstream_versions(connection, ws_row["id"])

    @staticmethod
    def _read_workstream_versions(connection: sqlite3.Connection, workstream_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT version, label, brief, constraints, created_at
            FROM workstream_versions
            WHERE workstream_id = ?
            ORDER BY version DESC
            """,
            (workstream_id,),
        ).fetchall()
        return [
            {
                "version": row["version"],
                "label": row["label"],
                "brief": row["brief"],
                "constraints": row["constraints"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

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
