"""Rendering tests for the goal-centric companion dashboard."""

from __future__ import annotations

from test_companion_dashboard import _goal, _to_text

from basecamp.companion.app import CompanionApp
from basecamp.companion.snapshot import CompanionTask
from basecamp.companion.ui.dashboard import (
    DashboardBody,
    _collapsed_goals_row,
    _goal_panel,
    _render_bullets,
    _render_task_detail,
)
from basecamp.companion.ui.formatting import _format_duration, _truncate_preview
from basecamp.companion.ui.modes import next_body_mode


def test_render_bullets_empty_shows_dash() -> None:
    assert _render_bullets([]).plain == "—"


def test_render_bullets_populated() -> None:
    plain = _render_bullets(["first", "second"]).plain
    assert "• first" in plain
    assert "• second" in plain


def test_truncate_preview_collapses_newlines_and_respects_limit() -> None:
    assert _truncate_preview("one\ntwo", max_length=20) == "one two"
    assert _truncate_preview("abcdef", max_length=4) == "abc…"


def test_format_duration_boundaries() -> None:
    assert _format_duration(59) == "59s"
    assert _format_duration(60) == "1m"
    assert _format_duration(3661) == "1h 1m"


def test_dashboard_css_uses_requested_row_ratios() -> None:
    css = CompanionApp.CSS
    assert "#dashboard-task {\n        height: 3fr;" in css
    assert "#dashboard-monitor {\n        height: 2fr;" in css
    assert "#dashboard-bottom {\n        height: 2fr;" in css
    assert "#dashboard-daemon" not in css


def test_swarm_css_includes_two_panel_layout() -> None:
    css = CompanionApp.CSS
    assert "#swarm-body" in css
    assert "#swarm-agents" in css
    assert "#swarm-detail" in css
    assert "#swarm-daemon" not in css


def test_render_bullets_preserves_literal_markup_text() -> None:
    assert "[bold]x[/]" in _render_bullets(["[bold]x[/]"]).plain


def test_goal_panel_marks_active_and_shows_progress() -> None:
    goal = _goal("Second goal", [], active=True, completed=0, total=2)
    text = _to_text(_goal_panel(goal, is_selected=True, is_active=True))
    assert "Second goal" in text
    assert "active" in text
    assert "0/2" in text


def test_goal_panel_preserves_literal_markup() -> None:
    goal = _goal("[bold]x[/]", [], active=False, completed=0, total=0)
    assert "[bold]x[/]" in _to_text(_goal_panel(goal, is_selected=False, is_active=False))


def test_goal_history_under_limit_has_no_collapse_row() -> None:
    goals = [_goal(f"Goal {index}", [], active=index == 5, completed=0, total=0) for index in range(6)]

    visible, collapsed = DashboardBody._visible_goal_indices(goals, active_index=5, selected_goal=5)

    assert visible == [0, 1, 2, 3, 4, 5]
    assert collapsed == 0


def test_goal_history_over_limit_shows_collapsed_count() -> None:
    goals = [_goal(f"Goal {index}", [], active=index == 7, completed=0, total=0) for index in range(8)]

    visible, collapsed = DashboardBody._visible_goal_indices(goals, active_index=7, selected_goal=7)

    assert visible == [2, 3, 4, 5, 6, 7]
    assert _collapsed_goals_row(collapsed).plain == "+ 2 hidden goals"


def test_goal_history_active_old_goal_remains_visible() -> None:
    goals = [_goal(f"Goal {index}", [], active=index == 0, completed=0, total=0) for index in range(8)]

    visible, collapsed = DashboardBody._visible_goal_indices(goals, active_index=0, selected_goal=0)

    assert visible == [0, 3, 4, 5, 6, 7]
    assert collapsed == 2


def test_goal_history_selected_hidden_goal_becomes_visible() -> None:
    goals = [_goal(f"Goal {index}", [], active=index == 7, completed=0, total=0) for index in range(8)]

    visible, collapsed = DashboardBody._visible_goal_indices(goals, active_index=7, selected_goal=0)

    assert visible == [0, 2, 3, 4, 5, 6, 7]
    assert collapsed == 1
    assert _collapsed_goals_row(collapsed).plain == "+ 1 hidden goal"


def test_render_task_detail_empty() -> None:
    assert "No tasks" in _to_text(_render_task_detail(None, 0))
    assert "No tasks" in _to_text(_render_task_detail(_goal("g", [], active=True, completed=0, total=0), 0))


def test_render_task_detail_shows_header_and_faded_annotation() -> None:
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
    text = _to_text(_render_task_detail(goal, 1))
    assert "[2/2]" in text
    assert "T2" in text
    assert "desc two" in text
    assert "a note" in text
    assert "note" in text


def test_next_body_mode_cycles_through_dashboard_diff_files_swarm() -> None:
    assert next_body_mode("dashboard-body") == "diff-body"
    assert next_body_mode("diff-body") == "files-body"
    assert next_body_mode("files-body") == "swarm-body"
    assert next_body_mode("swarm-body") == "dashboard-body"


def test_pinned_task_index_prefers_active() -> None:
    goal = _goal(
        "g",
        [
            CompanionTask(label="A", status="completed"),
            CompanionTask(label="B", status="active"),
            CompanionTask(label="C", status="pending"),
        ],
        active=True,
        completed=1,
        total=3,
    )
    assert DashboardBody._pinned_task_index(goal) == 1


def test_pinned_task_index_falls_back_to_last_when_all_completed() -> None:
    goal = _goal(
        "g",
        [CompanionTask(label="A", status="completed"), CompanionTask(label="B", status="completed")],
        active=False,
        completed=2,
        total=2,
    )
    assert DashboardBody._pinned_task_index(goal) == 1


def test_pinned_task_index_empty_goal_is_zero() -> None:
    assert DashboardBody._pinned_task_index(_goal("g", [], active=True, completed=0, total=0)) == 0
