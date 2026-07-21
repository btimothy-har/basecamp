"""Safe projections for file-backed goal cycles and tasks."""

from __future__ import annotations

import json
import os
from typing import Any

from .text import _display_text, _is_valid_agent_id

TASK_PLAN_LIMIT = 20
GOAL_STAGE_LIMIT = 10
TASK_LOG_MAX_BYTES = 256 * 1024
_TASK_STATUSES = {"pending", "active", "completed", "deleted"}
_AGENT_MODES = {"analysis", "planning", "work", "copilot"}


class TaskProjectionMixin:
    """Bounded reads of task-cycle files owned by session and agent ids."""

    def _read_task_cycles(self, agent_id: str) -> list[dict[str, Any]]:
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
            if metadata.st_size > TASK_LOG_MAX_BYTES:
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
        return self._project_task_log_from_cycles(self._read_task_cycles(agent_id))

    def _project_task_log_from_cycles(self, cycles: list[dict[str, Any]]) -> dict[str, Any] | None:
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
            if status not in _TASK_STATUSES:
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
            if len(tasks) < TASK_PLAN_LIMIT:
                tasks.append(task_row)
            if status == "active" and current_task is None:
                current_task = {
                    **task_row,
                    "description": _display_text(raw_task.get("description")),
                }

        return {
            "goal": _display_text(active.get("goal")),
            "progress": {"completed": completed, "deleted": deleted, "total": total},
            "task_plan": tasks,
            "current_task": current_task,
        }

    def _project_goal_stages(self, agent_id: str) -> dict[str, Any]:
        return self._project_goal_stages_from_cycles(self._read_task_cycles(agent_id))

    def _project_goal_stages_from_cycles(self, cycles: list[dict[str, Any]]) -> dict[str, Any]:
        indexed_cycles = list(enumerate(cycles))
        selected = indexed_cycles[-GOAL_STAGE_LIMIT:]
        return {
            "stages": [self._project_goal_stage(index, cycle) for index, cycle in selected],
            "stage_count": len(indexed_cycles),
            "stages_truncated": len(indexed_cycles) > GOAL_STAGE_LIMIT,
        }

    def _project_goal_stage(self, index: int, cycle: dict[str, Any]) -> dict[str, Any]:
        raw_tasks = cycle.get("tasks")
        if not isinstance(raw_tasks, list):
            raw_tasks = []

        tasks: list[dict[str, Any]] = []
        completed = 0
        deleted = 0
        total = 0
        for task_index, raw_task in enumerate(raw_tasks):
            if not isinstance(raw_task, dict):
                continue
            status = raw_task.get("status")
            if status not in _TASK_STATUSES:
                continue
            if status == "deleted":
                deleted += 1
                continue

            label = _display_text(raw_task.get("label"))
            if label is None:
                continue
            total += 1
            if status == "completed":
                completed += 1
            if len(tasks) >= TASK_PLAN_LIMIT:
                continue
            tasks.append(
                {
                    "index": task_index,
                    "label": label,
                    "description": _display_text(raw_task.get("description")),
                    "criteria": _display_text(raw_task.get("criteria")),
                    "status": status,
                }
            )

        agent_mode = cycle.get("agentMode")
        return {
            "index": index,
            "goal": _display_text(cycle.get("goal")),
            "active": cycle.get("active") is True,
            "archived_at": _display_text(cycle.get("archivedAt")),
            "agent_mode": agent_mode if agent_mode in _AGENT_MODES else None,
            "progress": {"completed": completed, "deleted": deleted, "total": total},
            "tasks": tasks,
            "tasks_truncated": total > TASK_PLAN_LIMIT,
        }
