"""Reads for the ``agents`` table."""

from __future__ import annotations

from typing import Any


class AgentsReaderMixin:
    """Agent registry queries."""

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Fetch an agent by id as a dict, or None when absent."""

        with self._reading() as connection:
            row = connection.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            return dict(row) if row is not None else None

    def get_agent_by_handle(self, agent_handle: str) -> dict[str, Any] | None:
        """Fetch an agent by public handle as a dict, or None when absent."""

        with self._reading() as connection:
            row = connection.execute("SELECT * FROM agents WHERE agent_handle = ?", (agent_handle,)).fetchone()
            return dict(row) if row is not None else None

    def get_subtree_agent_ids(self, root_agent_id: str) -> list[str]:
        """Return root agent id and all transitive descendant agent ids."""

        with self._reading() as connection:
            rows = connection.execute(
                """
                WITH RECURSIVE subtree(id) AS (
                    SELECT id FROM agents WHERE id = ?
                    UNION
                    SELECT a.id FROM agents a JOIN subtree s ON a.parent_id = s.id
                )
                SELECT id FROM subtree
                """,
                (root_agent_id,),
            ).fetchall()
            return [row[0] for row in rows]
