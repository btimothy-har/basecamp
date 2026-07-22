"""Safe global dashboard projections across recent root sessions."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from ._sqlite import load_json_column
from .text import (
    _display_text,
    _is_valid_agent_handle,
    _message_text,
    _preview_text,
)

DASHBOARD_ROOT_WINDOW_HOURS = 24
DASHBOARD_RECENT_ROOT_DEFAULT_LIMIT = 5
DASHBOARD_RECENT_ROOT_MAX_LIMIT = 50
DASHBOARD_AGENT_LIMIT = 100
DASHBOARD_MESSAGE_LIMIT = 3
DASHBOARD_MESSAGE_CHARS = 4000
DASHBOARD_RECURSION_LIMIT = DASHBOARD_AGENT_LIMIT + 1
_AGENT_MODES = {"analysis", "planning", "work", "copilot"}


class DashboardMixin:
    """Bounded read model for the authenticated localhost dashboard."""

    def get_dashboard_snapshot(
        self,
        *,
        live_node_ids: set[str] | None = None,
        recent_root_limit: int = DASHBOARD_RECENT_ROOT_DEFAULT_LIMIT,
        selected_root_handle: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        live = set(live_node_ids or ())
        safe_limit = max(0, min(recent_root_limit, DASHBOARD_RECENT_ROOT_MAX_LIMIT))
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        cutoff = current - timedelta(hours=DASHBOARD_ROOT_WINDOW_HOURS)
        eligible_rows = self._dashboard_root_rows(cutoff=cutoff, live_node_ids=live)
        root_rows, roots_truncated = self._select_dashboard_root_rows(
            eligible_rows,
            live_node_ids=live,
            recent_root_limit=safe_limit,
            selected_root_handle=selected_root_handle,
        )
        agent_rows = self._dashboard_agent_rows([row["id"] for row in root_rows])
        agents_by_root: dict[str, list[Any]] = defaultdict(list)
        for row in agent_rows:
            agents_by_root[row["root_id"]].append(row)

        with self._reading() as event_connection:
            roots = [
                self._project_dashboard_root(
                    row,
                    agents_by_root.get(row["id"], []),
                    event_connection=event_connection,
                    is_live=row["id"] in live,
                )
                for row in root_rows
            ]
        return {
            "generated_at": current.astimezone(UTC).isoformat(),
            "window_hours": DASHBOARD_ROOT_WINDOW_HOURS,
            "recent_root_limit": safe_limit,
            "recent_root_limit_max": DASHBOARD_RECENT_ROOT_MAX_LIMIT,
            "roots_truncated": roots_truncated,
            "roots": [root for root in roots if root is not None],
        }

    def _select_dashboard_root_rows(
        self,
        rows: list[Any],
        *,
        live_node_ids: set[str],
        recent_root_limit: int,
        selected_root_handle: str | None,
    ) -> tuple[list[Any], bool]:
        live_rows = [row for row in rows if row["id"] in live_node_ids]
        recent_rows = [row for row in rows if row["id"] not in live_node_ids]
        selected_recent = recent_rows[:recent_root_limit]
        selected_ids = {row["id"] for row in selected_recent}
        if selected_root_handle and _is_valid_agent_handle(selected_root_handle):
            pinned = next(
                (
                    row
                    for row in recent_rows
                    if row["agent_handle"] == selected_root_handle and row["id"] not in selected_ids
                ),
                None,
            )
            if pinned is not None:
                selected_recent.append(pinned)
                selected_ids.add(pinned["id"])
        roots_truncated = any(row["id"] not in selected_ids for row in recent_rows)
        return [*live_rows, *selected_recent], roots_truncated

    def _dashboard_root_rows(self, *, cutoff: datetime, live_node_ids: set[str]) -> list[Any]:
        live = sorted(live_node_ids)
        live_clause = f"a.id IN ({', '.join('?' for _ in live)})" if live else "0"
        query = f"""
            SELECT
                a.id,
                a.agent_handle,
                a.session_name,
                a.model,
                a.agent_mode,
                a.repo,
                a.worktree_label,
                a.branch,
                a.created_at,
                a.last_seen_at,
                CASE
                    WHEN a.agent_mode = 'copilot' THEN 'copilot'
                    WHEN EXISTS (
                        SELECT 1 FROM workstream_agents AS wa WHERE wa.agent_id = a.id
                    ) THEN 'workstream'
                    ELSE 'root'
                END AS kind
            FROM agents AS a
            WHERE a.parent_id IS NULL
              AND a.depth = 0
              AND a.role = 'agent'
              AND (julianday(a.last_seen_at) >= julianday(?) OR {live_clause})
            ORDER BY julianday(a.last_seen_at) DESC, a.agent_handle ASC
        """
        with self._reading() as connection:
            return connection.execute(query, (cutoff.astimezone(UTC).isoformat(), *live)).fetchall()

    def _dashboard_agent_rows(self, root_ids: list[str]) -> list[Any]:
        if not root_ids:
            return []
        roots = ", ".join("?" for _ in root_ids)
        query = f"""
            WITH RECURSIVE tree(root_id, id, tree_depth, path, hidden) AS (
                SELECT id, id, 0, '|' || hex(id) || '|', 0
                FROM agents
                WHERE id IN ({roots})
                UNION ALL
                SELECT
                    tree.root_id,
                    child.id,
                    tree.tree_depth + 1,
                    tree.path || hex(child.id) || '|',
                    CASE WHEN tree.hidden = 1 OR child.agent_type = 'ask' THEN 1 ELSE 0 END
                FROM tree
                INNER JOIN agents AS child ON child.parent_id = tree.id
                WHERE tree.tree_depth < ?
                  AND instr(tree.path, '|' || hex(child.id) || '|') = 0
            ),
            ranked AS (
                SELECT
                    tree.root_id,
                    tree.tree_depth,
                    a.id AS agent_id,
                    a.agent_handle,
                    parent.agent_handle AS parent_handle,
                    a.agent_type,
                    a.session_name,
                    a.model,
                    a.created_at AS agent_created_at,
                    a.last_seen_at,
                    r.id AS run_id,
                    CASE
                        WHEN r.status IN ('pending', 'running', 'completed', 'failed') THEN r.status
                        ELSE 'idle'
                    END AS status,
                    r.result,
                    r.error,
                    r.exit_code,
                    r.created_at AS run_created_at,
                    r.started_at,
                    r.ended_at,
                    COUNT(*) OVER (PARTITION BY tree.root_id) AS total_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY tree.root_id
                        ORDER BY tree.tree_depth ASC, COALESCE(r.created_at, a.created_at) ASC, a.agent_handle ASC
                    ) AS row_number
                FROM tree
                INNER JOIN agents AS a ON a.id = tree.id
                LEFT JOIN agents AS parent ON parent.id = a.parent_id
                LEFT JOIN runs AS r ON r.id = a.current_run_id
                WHERE tree.tree_depth > 0 AND tree.hidden = 0
            )
            SELECT * FROM ranked
            WHERE row_number <= ?
            ORDER BY root_id ASC, row_number ASC
        """
        params = (*root_ids, DASHBOARD_RECURSION_LIMIT, DASHBOARD_AGENT_LIMIT)
        with self._reading() as connection:
            return connection.execute(query, params).fetchall()

    def _project_dashboard_root(
        self,
        row: Any,
        agent_rows: list[Any],
        *,
        event_connection: sqlite3.Connection,
        is_live: bool,
    ) -> dict[str, Any] | None:
        raw_root_handle = row["agent_handle"]
        if not isinstance(raw_root_handle, str) or not _is_valid_agent_handle(raw_root_handle):
            return None
        root_handle = raw_root_handle
        cycles = self._read_task_cycles(row["id"])
        stages = self._project_goal_stages_from_cycles(cycles)
        task = self._project_task_log_from_cycles(cycles)
        agents: list[dict[str, Any]] = []
        for agent_row in agent_rows:
            projected = self._project_dashboard_agent(agent_row, event_connection=event_connection)
            if projected is not None:
                agents.append(projected)
        total_count = int(agent_rows[0]["total_count"]) if agent_rows else 0
        agent_mode = row["agent_mode"]
        return {
            "root_handle": root_handle,
            "kind": row["kind"],
            "session_name": _display_text(row["session_name"]),
            "model": _display_text(row["model"]),
            "agent_mode": agent_mode if agent_mode in _AGENT_MODES else None,
            "repo": _display_text(row["repo"]),
            "worktree_label": _display_text(row["worktree_label"]),
            "branch": _display_text(row["branch"]),
            "live": is_live,
            "created_at": _display_text(row["created_at"]),
            "last_seen_at": _display_text(row["last_seen_at"]),
            "task": task,
            **stages,
            "agent_count": total_count,
            "agents_truncated": total_count > DASHBOARD_AGENT_LIMIT,
            "agents": agents,
        }

    def _project_dashboard_agent(
        self,
        row: Any,
        *,
        event_connection: sqlite3.Connection,
    ) -> dict[str, Any] | None:
        raw_handle = row["agent_handle"]
        if not isinstance(raw_handle, str) or not _is_valid_agent_handle(raw_handle):
            return None
        activity = [
            event
            for event in self._project_recent_activity(row["run_id"], connection=event_connection)
            if event.get("kind") != "thinking"
        ]
        return {
            "agent_handle": raw_handle,
            "parent_handle": _display_text(row["parent_handle"]),
            "depth": row["tree_depth"],
            "agent_type": _display_text(row["agent_type"]),
            "session_name": _display_text(row["session_name"]),
            "model": _display_text(row["model"] or "default"),
            "status": row["status"],
            "created_at": _display_text(row["agent_created_at"]),
            "last_seen_at": _display_text(row["last_seen_at"]),
            "run_created_at": _display_text(row["run_created_at"]),
            "started_at": _display_text(row["started_at"]),
            "ended_at": _display_text(row["ended_at"]),
            "exit_code": row["exit_code"],
            "result_preview": _preview_text(row["result"]),
            "error_preview": _preview_text(row["error"]),
            "task": self._project_task_log(row["agent_id"]),
            "recent_activity": activity,
            "skills": self._project_skills(row["run_id"], connection=event_connection),
        }

    def get_dashboard_messages(
        self,
        *,
        root_handle: str,
        agent_handle: str,
        limit: int = DASHBOARD_MESSAGE_LIMIT,
    ) -> dict[str, Any]:
        safe_limit = max(0, min(limit, DASHBOARD_MESSAGE_LIMIT))
        response = {"root_handle": root_handle, "agent_handle": agent_handle, "messages": []}
        if not _is_valid_agent_handle(root_handle) or not _is_valid_agent_handle(agent_handle) or not safe_limit:
            return response

        with self._reading() as connection:
            agent = connection.execute(
                """
                WITH RECURSIVE scoped(id, path, depth, hidden) AS (
                    SELECT id, '|' || hex(id) || '|', 0, 0
                    FROM agents
                    WHERE agent_handle = ? AND parent_id IS NULL AND depth = 0 AND role = 'agent'
                    UNION ALL
                    SELECT
                        child.id,
                        scoped.path || hex(child.id) || '|',
                        scoped.depth + 1,
                        CASE WHEN scoped.hidden = 1 OR child.agent_type = 'ask' THEN 1 ELSE 0 END
                    FROM scoped
                    INNER JOIN agents AS child ON child.parent_id = scoped.id
                    WHERE scoped.depth < ?
                      AND instr(scoped.path, '|' || hex(child.id) || '|') = 0
                )
                SELECT a.current_run_id AS run_id
                FROM scoped
                INNER JOIN agents AS a ON a.id = scoped.id
                WHERE scoped.depth > 0 AND scoped.hidden = 0 AND a.agent_handle = ?
                LIMIT 1
                """,
                (root_handle, DASHBOARD_RECURSION_LIMIT, agent_handle),
            ).fetchone()
            if agent is None or not agent["run_id"]:
                return response
            rows = connection.execute(
                """
                SELECT seq, payload_json, ts
                FROM run_events
                WHERE run_id = ? AND kind = 'assistant_output'
                ORDER BY seq DESC
                LIMIT ?
                """,
                (agent["run_id"], safe_limit),
            ).fetchall()

        messages: list[dict[str, Any]] = []
        for row in reversed(rows):
            payload: Any = load_json_column(row["payload_json"], {})
            if not isinstance(payload, dict):
                continue
            text = _message_text(payload.get("text"))
            if text is None:
                continue
            truncated = len(text) > DASHBOARD_MESSAGE_CHARS
            if truncated:
                text = f"{text[: DASHBOARD_MESSAGE_CHARS - 1]}…"
            messages.append(
                {
                    "kind": "assistant_output",
                    "seq": row["seq"],
                    "timestamp": _display_text(row["ts"]),
                    "label": _display_text(payload.get("label")),
                    "text": text,
                    "truncated": truncated,
                }
            )
        response["messages"] = messages
        return response
