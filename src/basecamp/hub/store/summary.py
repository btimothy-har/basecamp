"""Run summary and message projection mixin."""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from .text import _agent_id_short, _display_text, _is_valid_agent_id, _message_text, _preview_text

RUN_SUMMARY_DEFAULT_LIMIT = 5
RUN_SUMMARY_MAX_LIMIT = 100
RUN_SUMMARY_TASK_PLAN_LIMIT = 20
RUN_MESSAGES_DEFAULT_LIMIT = 3
RUN_MESSAGES_MAX_LIMIT = 3
RUN_SUMMARY_ACTIVITY_LIMIT = 10
RUN_SUMMARY_SKILLS_LIMIT = 20
RUN_SUMMARY_TASK_LOG_MAX_BYTES = 256 * 1024
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
    """Sanitized run summary, activity, skills, and message projections."""

    def _read_task_cycles(self, agent_id: str) -> list[dict[str, Any]]:
        """Safely read task cycles for an internal agent id."""

        if not _is_valid_agent_id(agent_id):
            return []

        task_path = self.task_dir / f"{agent_id}.json"
        try:
            root = self.task_dir.resolve(strict=False)
            candidate = task_path.resolve(strict=False)
            if root != candidate.parent:
                return []

            metadata = os.lstat(task_path)
            if not os.path.isfile(task_path) or os.path.islink(task_path):
                return []
            if metadata.st_size > RUN_SUMMARY_TASK_LOG_MAX_BYTES:
                return []

            with task_path.open("r", encoding="utf-8") as file:
                parsed = json.load(file)
        except (OSError, json.JSONDecodeError):
            return []

        if isinstance(parsed, dict):
            parsed = parsed.get("cycles")
        if not isinstance(parsed, list):
            return []
        return [cycle for cycle in parsed if isinstance(cycle, dict)]

    def _project_task_log(self, agent_id: str) -> dict[str, Any] | None:
        cycles = self._read_task_cycles(agent_id)
        active = next((cycle for cycle in cycles if cycle.get("active") is True), None)
        if active is None:
            return None

        raw_tasks = active.get("tasks")
        if not isinstance(raw_tasks, list):
            return None

        tasks: list[dict[str, Any]] = []
        current_task: dict[str, Any] | None = None
        deleted = 0
        completed = 0
        total = 0
        for index, raw_task in enumerate(raw_tasks):
            if not isinstance(raw_task, dict):
                continue
            status = raw_task.get("status")
            if status not in {"pending", "active", "completed", "deleted"}:
                continue
            if status == "deleted":
                deleted += 1
                continue

            label = _display_text(raw_task.get("label"))
            if label is None:
                continue
            if status == "completed":
                completed += 1
            total += 1
            task_row = {"index": index, "label": label, "status": status}
            if len(tasks) < RUN_SUMMARY_TASK_PLAN_LIMIT:
                tasks.append(task_row)
            if status == "active" and current_task is None:
                current_task = {
                    **task_row,
                    "description": _display_text(raw_task.get("description")),
                }

        return {
            "goal": _display_text(active.get("goal")),
            "progress": {
                "completed": completed,
                "deleted": deleted,
                "total": total,
            },
            "task_plan": tasks,
            "current_task": current_task,
        }

    def _project_recent_activity(self, run_id: str | None) -> list[dict[str, Any]]:
        if not run_id:
            return []

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT seq, kind, payload_json, ts
                FROM run_events
                WHERE run_id = ?
                ORDER BY seq DESC
                LIMIT ?
                """,
                (run_id, RUN_SUMMARY_ACTIVITY_LIMIT),
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
            payload: Any = {}
            try:
                payload = json.loads(row["payload_json"]) if isinstance(row["payload_json"], str) else {}
            except json.JSONDecodeError:
                payload = {}
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

    def _project_skills(self, run_id: str | None) -> list[dict[str, Any]]:
        if not run_id:
            return []

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT seq, payload_json, ts
                FROM run_events
                WHERE run_id = ?
                  AND kind = 'tool_call'
                ORDER BY seq ASC
                """,
                (run_id,),
            ).fetchall()

        skills: dict[str, dict[str, Any]] = {}
        for row in rows:
            payload: Any = {}
            try:
                payload = json.loads(row["payload_json"]) if isinstance(row["payload_json"], str) else {}
            except json.JSONDecodeError:
                payload = {}
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

        return sorted(skills.values(), key=lambda skill: skill["last_seq"], reverse=True)[:RUN_SUMMARY_SKILLS_LIMIT]

    def get_run_messages(
        self,
        root_id: str,
        *,
        agent_handle: str,
        limit: int = RUN_MESSAGES_DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        """Return latest visible assistant messages for one scoped agent."""

        safe_limit = max(0, min(limit, RUN_MESSAGES_MAX_LIMIT))
        messages: list[dict[str, Any]] = []

        recursive_scope = """
            WITH RECURSIVE scoped_agents(id) AS (
                SELECT id FROM agents WHERE id = ?
                UNION
                SELECT child.id
                FROM agents AS child
                INNER JOIN scoped_agents AS parent ON child.parent_id = parent.id
            )
        """

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            agent_row = connection.execute(
                f"""
                {recursive_scope}
                SELECT
                    a.agent_handle,
                    r.id AS run_id,
                    r.result,
                    r.ended_at
                FROM agents AS a
                INNER JOIN scoped_agents AS s ON s.id = a.id
                LEFT JOIN runs AS r ON r.id = a.current_run_id
                WHERE a.agent_handle = ?
                  AND a.role != 'agent'
                LIMIT 1
                """,
                (root_id, agent_handle),
            ).fetchone()

            if agent_row is not None and agent_row["run_id"] and safe_limit:
                rows = connection.execute(
                    """
                    SELECT seq, payload_json, ts
                    FROM run_events
                    WHERE run_id = ?
                      AND kind = 'assistant_output'
                    ORDER BY seq DESC
                    LIMIT ?
                    """,
                    (agent_row["run_id"], safe_limit),
                ).fetchall()

                for row in reversed(rows):
                    payload: Any = {}
                    try:
                        payload = json.loads(row["payload_json"]) if isinstance(row["payload_json"], str) else {}
                    except json.JSONDecodeError:
                        payload = {}
                    if not isinstance(payload, dict):
                        continue
                    text = _message_text(payload.get("text"))
                    if text is None:
                        continue
                    messages.append(
                        {
                            "kind": "assistant_output",
                            "seq": row["seq"],
                            "timestamp": _display_text(row["ts"]),
                            "label": _display_text(payload.get("label")),
                            "text": text,
                        }
                    )

                result_text = _message_text(agent_row["result"])
                if result_text is not None and (not messages or messages[-1]["text"] != result_text):
                    messages.append(
                        {
                            "kind": "agent_result",
                            "seq": None,
                            "timestamp": _display_text(agent_row["ended_at"]),
                            "label": "result",
                            "text": result_text,
                        }
                    )

        return {
            "root_id": root_id,
            "agent_handle": agent_handle,
            "messages": messages[-safe_limit:] if safe_limit else [],
        }

    def get_run_summary(self, root_id: str, *, limit: int = RUN_SUMMARY_DEFAULT_LIMIT) -> dict[str, Any]:
        """Return a safe run summary for a root agent subtree."""

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

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row

            counts_row = connection.execute(
                f"""
                {recursive_scope}
                SELECT
                    COALESCE(SUM(CASE WHEN r.status = 'pending' THEN 1 ELSE 0 END), 0) AS pending_count,
                    COALESCE(SUM(CASE WHEN r.status = 'running' THEN 1 ELSE 0 END), 0) AS running_count,
                    COALESCE(SUM(CASE WHEN r.status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_count,
                    COALESCE(SUM(CASE WHEN r.status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_count,
                    COUNT(r.id) AS total_count
                FROM runs AS r
                WHERE r.agent_id IN (SELECT id FROM scoped_agents)
                """,
                (root_id,),
            ).fetchone()

            agent_rows = connection.execute(
                f"""
                {recursive_scope}
                SELECT
                    a.id AS agent_id,
                    a.agent_handle,
                    a.agent_type,
                    a.model,
                    a.role,
                    a.session_name,
                    r.id AS run_id,
                    CASE
                        WHEN r.status IN ('pending', 'running', 'completed', 'failed') THEN r.status
                        ELSE 'idle'
                    END AS status,
                    r.result,
                    r.error,
                    r.exit_code,
                    r.created_at,
                    r.started_at,
                    r.ended_at
                FROM agents AS a
                INNER JOIN scoped_agents AS s ON s.id = a.id
                LEFT JOIN runs AS r ON r.id = a.current_run_id
                WHERE a.role != 'agent'
                ORDER BY COALESCE(r.created_at, a.created_at) DESC, a.agent_handle ASC
                LIMIT ?
                """,
                (root_id, safe_limit),
            ).fetchall()

        agents = [
            {
                "agent_handle": _display_text(row["agent_handle"]),
                "agent_id_short": _agent_id_short(row["agent_id"]),
                "agent_type": _display_text(row["agent_type"]),
                "model": _display_text(row["model"] or "default"),
                "role": _display_text(row["role"]),
                "session_name": _display_text(row["session_name"]),
                "status": row["status"],
                "result_preview": _preview_text(row["result"]),
                "error_preview": _preview_text(row["error"]),
                "exit_code": row["exit_code"],
                "created_at": _display_text(row["created_at"]),
                "started_at": _display_text(row["started_at"]),
                "ended_at": _display_text(row["ended_at"]),
                "task": self._project_task_log(row["agent_id"]),
                "recent_activity": self._project_recent_activity(row["run_id"]),
                "skills": self._project_skills(row["run_id"]),
            }
            for row in agent_rows
        ]

        return {
            "root_id": root_id,
            "counts": {
                "pending": counts_row["pending_count"],
                "running": counts_row["running_count"],
                "completed": counts_row["completed_count"],
                "failed": counts_row["failed_count"],
                "total": counts_row["total_count"],
            },
            "agents": agents,
        }
