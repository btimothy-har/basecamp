"""Tests for the goal-centric companion dashboard."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from basecamp.companion.app import (
    CompanionApp,
    DashboardBody,
    _render_bullets,
    _render_goal_lines,
    _render_task_detail,
    next_body_mode,
)
from basecamp.companion.snapshot import CompanionGoal, CompanionProgress, CompanionSnapshot, CompanionTask
from textual.widgets import ContentSwitcher, Static


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)  # noqa: S603


def _build_repo(repo: Path) -> None:
    repo.mkdir()
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.email", "smoke@example.com")
    _run_git(repo, "config", "user.name", "Smoke Test")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "base commit")


def _goal(name: str, tasks: list[CompanionTask], *, active: bool, completed: int, total: int) -> CompanionGoal:
    return CompanionGoal(
        goal=name,
        tasks=tasks,
        agent_mode=None,
        active=active,
        archived_at=None if active else "2025-01-01T00:00:00Z",
        progress=CompanionProgress(completed=completed, total=total),
    )


def test_render_bullets_empty_shows_dash() -> None:
    assert _render_bullets([]).plain == "—"


def test_render_bullets_populated() -> None:
    plain = _render_bullets(["first", "second"]).plain
    assert "• first" in plain
    assert "• second" in plain


def test_render_bullets_preserves_literal_markup_text() -> None:
    assert "[bold]x[/]" in _render_bullets(["[bold]x[/]"]).plain


def test_render_goal_lines_empty() -> None:
    assert _render_goal_lines([], 0, None).plain == "No goals yet"


def test_render_goal_lines_marks_active_and_lists_all() -> None:
    goals = [
        _goal("First goal", [], active=False, completed=1, total=1),
        _goal("Second goal", [], active=True, completed=0, total=2),
    ]
    plain = _render_goal_lines(goals, 1, 1).plain
    assert "First goal" in plain
    assert "Second goal" in plain
    assert "●" in plain  # active marker
    assert "[0/2]" in plain


def test_render_task_detail_empty() -> None:
    assert _render_task_detail(None, 0).plain == "No tasks"
    assert _render_task_detail(_goal("g", [], active=True, completed=0, total=0), 0).plain == "No tasks"


def test_render_task_detail_shows_label_description_notes_and_position() -> None:
    goal = _goal(
        "g",
        [
            CompanionTask(label="T1", status="completed", description="d1", criteria="c1", notes=None),
            CompanionTask(label="T2", status="active", description="desc two", criteria="c2", notes="a note"),
        ],
        active=True,
        completed=1,
        total=2,
    )
    plain = _render_task_detail(goal, 1).plain
    assert "[2/2]" in plain
    assert "T2" in plain
    assert "desc two" in plain
    assert "a note" in plain


def test_next_body_mode_cycles_three_way() -> None:
    assert next_body_mode("diff-body") == "files-body"
    assert next_body_mode("files-body") == "dashboard-body"
    assert next_body_mode("dashboard-body") == "diff-body"


def test_dashboard_autopin_navigation_and_repin(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "sessionId": "abcd-1234-5678-90ef",
                "updatedAt": "2026-06-04T12:35:00Z",
                "effectiveCwd": str(repo),
                "goals": [
                    {
                        "goal": "First goal",
                        "tasks": [
                            {
                                "label": "T1",
                                "description": "d1",
                                "criteria": "c1",
                                "status": "completed",
                                "notes": "n1",
                            },
                            {
                                "label": "T2",
                                "description": "d2",
                                "criteria": "c2",
                                "status": "completed",
                                "notes": None,
                            },
                        ],
                        "agentMode": "executor",
                        "active": False,
                        "archivedAt": "2025-01-01T00:00:00Z",
                        "progress": {"completed": 2, "total": 2},
                    },
                    {
                        "goal": "Second goal",
                        "tasks": [
                            {
                                "label": "T3",
                                "description": "d3",
                                "criteria": "c3",
                                "status": "completed",
                                "notes": None,
                            },
                            {
                                "label": "T4",
                                "description": "d4",
                                "criteria": "c4",
                                "status": "active",
                                "notes": "wip",
                            },
                        ],
                        "agentMode": None,
                        "active": True,
                        "archivedAt": None,
                        "progress": {"completed": 1, "total": 2},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    analysis_path = snapshot_path.parent / f"{snapshot_path.stem}.analysis.json"
    analysis_path.write_text(
        json.dumps(
            {
                "version": 1,
                "sessionId": "abcd-1234-5678-90ef",
                "updatedAt": "2026-06-04T12:35:00Z",
                "decisions": ["dec1"],
                "openItems": ["open1"],
                "warnings": ["warn1"],
            }
        ),
        encoding="utf-8",
    )

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.25)
            switcher = app.query_one("#body", ContentSwitcher)
            await pilot.press("m")
            await pilot.pause(0.1)
            assert switcher.current == "dashboard-body"

            dash = app.query_one("#dashboard-body", DashboardBody)
            assert dash.has_focus
            for box_id in (
                "#dashboard-goals",
                "#dashboard-task",
                "#dashboard-decisions",
                "#dashboard-open",
                "#dashboard-warnings",
            ):
                app.query_one(box_id, Static)

            assert dash._active_index == 1
            assert dash._following is True
            assert dash._selected_goal == 1
            assert dash._selected_task == 1

            dash.action_goal_prev()
            assert dash._selected_goal == 0
            assert dash._following is False
            assert dash._selected_task == 0

            dash.action_task_next()
            assert dash._selected_task == 1
            assert dash._following is False

            repinned = CompanionSnapshot(
                version=1,
                session_id="abcd-1234-5678-90ef",
                updated_at="2026-06-04T12:36:00Z",
                goals=[
                    _goal("First goal", [], active=False, completed=2, total=2),
                    _goal("Second goal", [], active=False, completed=2, total=2),
                    _goal(
                        "Third goal",
                        [CompanionTask(label="T5", status="active")],
                        active=True,
                        completed=0,
                        total=1,
                    ),
                ],
            )
            dash.update_snapshot(repinned)
            assert dash._active_index == 2
            assert dash._following is True
            assert dash._selected_goal == 2

    asyncio.run(run())
