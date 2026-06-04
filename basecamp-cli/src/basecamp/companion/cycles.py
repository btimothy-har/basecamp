"""Direct read of basecamp's goal-cycle store (~/.pi/tasks/<session-id>.json).

The companion dashboard reads goal/task state straight from this file — the
single source of truth written by pi-extension/src/workflow/tasks/tasks.ts as a
JSON array of GoalCycle objects. This module mirrors that on-disk shape and is
deliberately tolerant (extra keys ignored, best-effort load) because tasks.ts
owns the schema.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field, ValidationError

from basecamp.companion.snapshot import (
    CompanionBaseModel,
    CompanionGoal,
    CompanionProgress,
    CompanionTask,
)


class TaskCycle(CompanionBaseModel):
    """A persisted goal cycle (raw — still includes deleted tasks)."""

    goal: str
    tasks: list[CompanionTask] = Field(default_factory=list)
    agent_mode: str | None = None
    active: bool = False
    archived_at: str | None = None


def companion_tasks_path(session_id: str, base_dir: Path | None = None) -> Path:
    """Path to the goal-cycle store for a session (raw session id, matching tasks.ts)."""

    resolved_base_dir = base_dir or (Path.home() / ".pi" / "tasks")
    return resolved_base_dir / f"{session_id}.json"


def _validate_cycle(item: object) -> TaskCycle | None:
    """Validate one raw cycle item, returning None when invalid."""

    try:
        return TaskCycle.model_validate(item)
    except ValidationError:
        return None


def load_goal_cycles(path: Path) -> list[TaskCycle]:
    """Best-effort load of the goal-cycle store; returns [] on any failure."""

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(parsed, list):
        return []

    cycles: list[TaskCycle] = []
    for item in parsed:
        cycle = _validate_cycle(item)
        if cycle is not None:
            cycles.append(cycle)
    return cycles


def to_display_goals(cycles: list[TaskCycle]) -> list[CompanionGoal]:
    """Map raw cycles to dashboard goals: drop deleted tasks, compute progress."""

    goals: list[CompanionGoal] = []
    for cycle in cycles:
        live = [task for task in cycle.tasks if task.status != "deleted"]
        completed = sum(1 for task in live if task.status == "completed")
        goals.append(
            CompanionGoal(
                goal=cycle.goal,
                tasks=live,
                agent_mode=cycle.agent_mode,
                active=cycle.active,
                archived_at=cycle.archived_at,
                progress=CompanionProgress(completed=completed, total=len(live)),
            )
        )
    return goals
