"""Writes for the ``agents`` table."""

from __future__ import annotations

import sqlite3

from ..errors import DuplicateAgentHandleError
from ..text import _fallback_agent_handle, safe_product_role


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
        run_kind: str | None = None,
        model: str | None = None,
        session_file: str | None = None,
        product_role: str | None = None,
        repo: str | None = None,
        worktree_label: str | None = None,
    ) -> None:
        """Insert/update an agent row and refresh last-seen timestamp."""

        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT agent_handle, agent_type, run_kind, model, sibling_group, session_file, product_role
                FROM agents
                WHERE id = ?
                """,
                (agent_id,),
            ).fetchone()
            stored_handle = existing[0] if existing is not None else None
            stored_agent_type = existing[1] if existing is not None else None
            stored_run_kind = existing[2] if existing is not None else None
            stored_model = existing[3] if existing is not None else None
            stored_sibling_group = existing[4] if existing is not None else None
            stored_session_file = existing[5] if existing is not None else None
            stored_product_role = existing[6] if existing is not None else None
            next_handle = agent_handle or stored_handle or _fallback_agent_handle(agent_id)
            next_agent_type = agent_type or stored_agent_type
            next_run_kind = run_kind or stored_run_kind
            next_model = model or stored_model
            next_sibling_group = sibling_group or stored_sibling_group
            next_session_file = session_file or stored_session_file
            next_product_role = safe_product_role(product_role) or stored_product_role

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
                        run_kind,
                        model,
                        session_file,
                        product_role,
                        repo,
                        worktree_label
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
                        run_kind = excluded.run_kind,
                        model = excluded.model,
                        session_file = excluded.session_file,
                        product_role = excluded.product_role,
                        repo = excluded.repo,
                        worktree_label = excluded.worktree_label
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
                        next_run_kind,
                        next_model,
                        next_session_file,
                        next_product_role,
                        repo,
                        worktree_label,
                    ),
                )
            except sqlite3.IntegrityError as error:
                if "agents.agent_handle" in str(error):
                    raise DuplicateAgentHandleError(next_handle) from error
                raise
