"""Writes for the ``agents`` table."""

from __future__ import annotations

import sqlite3

from ..errors import DuplicateAgentHandleError
from ..text import _fallback_agent_handle


class AgentsWriterMixin:
    """Agent registry mutations."""

    def upsert_agent(
        self,
        *,
        agent_id: str,
        parent_id: str | None,
        sibling_group: str | None,
        depth: int,
        role: str,
        session_name: str,
        cwd: str,
        agent_handle: str | None = None,
        agent_type: str | None = None,
        model: str | None = None,
        session_file: str | None = None,
        repo: str | None = None,
        worktree_label: str | None = None,
        branch: str | None = None,
        agent_mode: str | None = None,
    ) -> None:
        """Insert/update an agent row and refresh last-seen timestamp."""

        now = self._now()
        with self._writing(immediate=True) as connection:
            existing = connection.execute(
                """
                SELECT agent_handle, agent_type, model, sibling_group, session_file,
                       repo, worktree_label, branch, agent_mode
                FROM agents
                WHERE id = ?
                """,
                (agent_id,),
            ).fetchone()
            stored_handle = existing[0] if existing is not None else None
            stored_agent_type = existing[1] if existing is not None else None
            stored_model = existing[2] if existing is not None else None
            stored_sibling_group = existing[3] if existing is not None else None
            stored_session_file = existing[4] if existing is not None else None
            stored_repo = existing[5] if existing is not None else None
            stored_worktree_label = existing[6] if existing is not None else None
            stored_branch = existing[7] if existing is not None else None
            stored_agent_mode = existing[8] if existing is not None else None
            next_handle = agent_handle or stored_handle or _fallback_agent_handle(agent_id)
            next_agent_type = agent_type or stored_agent_type
            next_model = model or stored_model
            next_sibling_group = sibling_group or stored_sibling_group
            next_session_file = session_file or stored_session_file
            next_repo = repo or stored_repo
            next_worktree_label = worktree_label or stored_worktree_label
            next_branch = branch or stored_branch
            next_agent_mode = agent_mode or stored_agent_mode

            try:
                connection.execute(
                    """
                    INSERT INTO agents (
                        id,
                        parent_id,
                        sibling_group,
                        depth,
                        role,
                        session_name,
                        cwd,
                        created_at,
                        last_seen_at,
                        agent_handle,
                        agent_type,
                        model,
                        session_file,
                        repo,
                        worktree_label,
                        branch,
                        agent_mode
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id)
                    DO UPDATE SET
                        parent_id = excluded.parent_id,
                        sibling_group = excluded.sibling_group,
                        depth = excluded.depth,
                        role = excluded.role,
                        session_name = excluded.session_name,
                        cwd = excluded.cwd,
                        last_seen_at = excluded.last_seen_at,
                        agent_handle = excluded.agent_handle,
                        agent_type = excluded.agent_type,
                        model = excluded.model,
                        session_file = excluded.session_file,
                        repo = excluded.repo,
                        worktree_label = excluded.worktree_label,
                        branch = excluded.branch,
                        agent_mode = excluded.agent_mode
                    """,
                    (
                        agent_id,
                        parent_id,
                        next_sibling_group,
                        depth,
                        role,
                        session_name,
                        cwd,
                        now,
                        now,
                        next_handle,
                        next_agent_type,
                        next_model,
                        next_session_file,
                        next_repo,
                        next_worktree_label,
                        next_branch,
                        next_agent_mode,
                    ),
                )
            except sqlite3.IntegrityError as error:
                if "agents.agent_handle" in str(error):
                    raise DuplicateAgentHandleError(next_handle) from error
                raise

    def update_agent_metadata(
        self,
        *,
        agent_id: str,
        session_name: str,
        model: str | None,
        agent_mode: str,
        repo: str | None,
        worktree_label: str | None,
        branch: str | None,
    ) -> None:
        """Replace mutable session metadata, including explicit null values."""

        with self._writing() as connection:
            connection.execute(
                """
                UPDATE agents
                SET session_name = ?, model = ?, agent_mode = ?, repo = ?,
                    worktree_label = ?, branch = ?, last_seen_at = ?
                WHERE id = ?
                """,
                (
                    session_name,
                    model,
                    agent_mode,
                    repo,
                    worktree_label,
                    branch,
                    self._now(),
                    agent_id,
                ),
            )

    def touch_agent(self, agent_id: str) -> None:
        """Refresh an agent's last-seen timestamp."""

        with self._writing() as connection:
            connection.execute(
                "UPDATE agents SET last_seen_at = ? WHERE id = ?",
                (self._now(), agent_id),
            )
