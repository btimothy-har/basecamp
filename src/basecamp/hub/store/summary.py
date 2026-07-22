"""Compact run summaries plus shared activity and skill projections."""

from __future__ import annotations

import sqlite3
from typing import Any

from ._sqlite import load_json_column
from .text import _display_text

RUN_SUMMARY_DEFAULT_LIMIT = 5
RUN_SUMMARY_MAX_LIMIT = 50
RECENT_ACTIVITY_LIMIT = 10
SKILLS_LIMIT = 20
SKILL_EVENT_LIMIT = 1000
_ACTIVITY_KINDS = {
    "tool_call",
    "tool_result",
    "assistant_output",
    "thinking",
    "agent_result",
    "tool_execution_start",
    "tool_execution_end",
    "turn_end",
}
_ACTIVITY_PAYLOAD_KEYS = ("category", "label", "snippet", "toolName", "isError", "turnIndex", "toolCount")


class SummaryMixin:
    """Safe widget summaries and dashboard activity projections."""

    def _project_recent_activity(
        self,
        run_id: str | None,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        if not run_id:
            return []
        if connection is None:
            with self._reading() as owned_connection:
                return self._project_recent_activity(run_id, connection=owned_connection)

        rows = connection.execute(
            """
            SELECT seq, kind, payload_json, ts
            FROM run_events
            WHERE run_id = ?
            ORDER BY seq DESC
            LIMIT ?
            """,
            (run_id, RECENT_ACTIVITY_LIMIT),
        ).fetchall()

        activity: list[dict[str, Any]] = []
        for row in reversed(rows):
            kind = row["kind"]
            if kind not in _ACTIVITY_KINDS:
                continue
            event: dict[str, Any] = {
                "kind": kind,
                "seq": row["seq"],
                "timestamp": _display_text(row["ts"]),
            }
            payload: Any = load_json_column(row["payload_json"], {})
            if isinstance(payload, dict):
                for key in _ACTIVITY_PAYLOAD_KEYS:
                    value = payload.get(key)
                    if key == "isError":
                        if isinstance(value, bool):
                            event[key] = value
                    elif isinstance(value, str):
                        event[key] = _display_text(value)
                    elif isinstance(value, int | float) and not isinstance(value, bool):
                        event[key] = value
            activity.append({key: value for key, value in event.items() if value is not None})
        return activity

    def _project_skills(
        self,
        run_id: str | None,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        if not run_id:
            return []
        if connection is None:
            with self._reading() as owned_connection:
                return self._project_skills(run_id, connection=owned_connection)

        rows = connection.execute(
            """
            SELECT seq, payload_json, ts
            FROM run_events
            WHERE run_id = ?
              AND kind = 'tool_call'
            ORDER BY seq DESC
            LIMIT ?
            """,
            (run_id, SKILL_EVENT_LIMIT),
        ).fetchall()

        skills: dict[str, dict[str, Any]] = {}
        for row in reversed(rows):
            payload: Any = load_json_column(row["payload_json"], {})
            if not isinstance(payload, dict) or payload.get("toolName") != "skill":
                continue

            name = _display_text(payload.get("skillName"))
            snippet = payload.get("snippet")
            if not name and isinstance(snippet, str) and snippet.startswith("skill "):
                name = _display_text(snippet.removeprefix("skill "))
            if not name:
                continue

            skill = skills.setdefault(
                name,
                {
                    "name": name,
                    "count": 0,
                    "last_seq": row["seq"],
                    "last_timestamp": _display_text(row["ts"]),
                },
            )
            skill["count"] += 1
            skill["last_seq"] = row["seq"]
            skill["last_timestamp"] = _display_text(row["ts"])

        return sorted(skills.values(), key=lambda skill: skill["last_seq"], reverse=True)[:SKILLS_LIMIT]

    def _project_summary_task(self, agent_id: str) -> dict[str, Any] | None:
        task = self._project_task_log(agent_id)
        if task is None:
            return None
        current_task = task.get("current_task")
        return {
            "goal": task.get("goal"),
            "current_task": {"label": current_task.get("label")} if isinstance(current_task, dict) else None,
        }

    def get_run_summary(self, root_id: str, *, limit: int = RUN_SUMMARY_DEFAULT_LIMIT) -> dict[str, Any]:
        """Return compact active-agent widget rows for a root subtree."""

        safe_limit = max(0, min(limit, RUN_SUMMARY_MAX_LIMIT))
        recursive_scope = """
            WITH RECURSIVE scoped_agents(id) AS (
                SELECT id FROM agents WHERE id = ?
                UNION
                SELECT child.id
                FROM agents AS child
                INNER JOIN scoped_agents AS parent ON child.parent_id = parent.id
            )
        """

        with self._reading() as connection:
            agent_rows = connection.execute(
                f"""
                {recursive_scope}
                SELECT
                    a.id AS agent_id,
                    a.agent_handle,
                    a.agent_type,
                    a.session_name,
                    CASE
                        WHEN r.status IN ('pending', 'running', 'completed', 'failed') THEN r.status
                        ELSE 'idle'
                    END AS status,
                    r.created_at,
                    r.started_at
                FROM agents AS a
                INNER JOIN scoped_agents AS s ON s.id = a.id
                LEFT JOIN runs AS r ON r.id = a.current_run_id
                WHERE a.role != 'agent'
                ORDER BY COALESCE(r.created_at, a.created_at) DESC, a.agent_handle ASC
                LIMIT ?
                """,
                (root_id, safe_limit),
            ).fetchall()

        return {
            "agents": [
                {
                    "agent_handle": _display_text(row["agent_handle"]),
                    "agent_type": _display_text(row["agent_type"]),
                    "session_name": _display_text(row["session_name"]),
                    "status": row["status"],
                    "created_at": _display_text(row["created_at"]),
                    "started_at": _display_text(row["started_at"]),
                    "task": self._project_summary_task(row["agent_id"]),
                }
                for row in agent_rows
            ]
        }
