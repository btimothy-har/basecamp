"""Tests for the direct goal-cycle store reader."""

from __future__ import annotations

import json
from pathlib import Path

from companion_tui.cycles import (
    TaskCycle,
    companion_tasks_path,
    load_goal_cycles,
    to_display_goals,
)


def _write_cycles(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_companion_tasks_path_uses_raw_session_id() -> None:
    path = companion_tasks_path("abc-123", base_dir=Path("/tmp/tasks"))
    assert path == Path("/tmp/tasks/abc-123.json")


def test_load_goal_cycles_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_goal_cycles(tmp_path / "nope.json") == []


def test_load_goal_cycles_corrupt_json_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_goal_cycles(path) == []


def test_load_goal_cycles_non_list_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "obj.json"
    _write_cycles(path, {"goal": "x"})
    assert load_goal_cycles(path) == []


def test_load_goal_cycles_parses_and_ignores_extra_keys(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    _write_cycles(
        path,
        [
            {
                "goal": "First goal",
                "tasks": [
                    {
                        "label": "T1",
                        "description": "d1",
                        "criteria": "c1",
                        "notes": "n1",
                        "status": "completed",
                        "review": None,
                    },
                    {"label": "T2", "description": "", "criteria": "", "notes": None, "status": "deleted"},
                ],
                "planRef": None,
                "agentMode": "executor",
                "active": False,
                "archivedAt": "2025-01-01T00:00:00Z",
            },
            {
                "goal": "Second goal",
                "tasks": [{"label": "T3", "status": "active", "notes": None}],
                "agentMode": None,
                "active": True,
                "archivedAt": None,
            },
        ],
    )

    cycles = load_goal_cycles(path)
    assert len(cycles) == 2
    assert isinstance(cycles[0], TaskCycle)
    assert cycles[0].goal == "First goal"
    assert cycles[0].agent_mode == "executor"
    assert cycles[0].archived_at == "2025-01-01T00:00:00Z"
    assert cycles[0].tasks[0].description == "d1"
    assert cycles[1].active is True


def test_to_display_goals_filters_deleted_and_computes_progress(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    _write_cycles(
        path,
        [
            {
                "goal": "G",
                "tasks": [
                    {"label": "A", "status": "completed", "notes": None},
                    {"label": "B", "status": "deleted", "notes": None},
                    {"label": "C", "status": "active", "notes": None},
                ],
                "active": True,
                "archivedAt": None,
            }
        ],
    )

    goals = to_display_goals(load_goal_cycles(path))
    assert len(goals) == 1
    goal = goals[0]
    assert [task.label for task in goal.tasks] == ["A", "C"]
    assert goal.progress.completed == 1
    assert goal.progress.total == 2
    assert goal.active is True
