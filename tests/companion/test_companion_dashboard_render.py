"""Rendering tests for the analysis-only companion dashboard."""

from __future__ import annotations

from basecamp.companion.app import CompanionApp
from basecamp.companion.ui.dashboard import _render_bullets
from basecamp.companion.ui.formatting import _format_duration, _truncate_preview
from basecamp.companion.ui.modes import next_body_mode


def test_render_bullets_empty_shows_dash() -> None:
    assert _render_bullets([]).plain == "—"


def test_render_bullets_populated() -> None:
    plain = _render_bullets(["first", "second"]).plain
    assert "• first" in plain
    assert "• second" in plain


def test_render_bullets_preserves_literal_markup_text() -> None:
    assert "[bold]x[/]" in _render_bullets(["[bold]x[/]"]).plain


def test_truncate_preview_collapses_newlines_and_respects_limit() -> None:
    assert _truncate_preview("one\ntwo", max_length=20) == "one two"
    assert _truncate_preview("abcdef", max_length=4) == "abc…"


def test_format_duration_boundaries() -> None:
    assert _format_duration(59) == "59s"
    assert _format_duration(60) == "1m"
    assert _format_duration(3661) == "1h 1m"


def test_dashboard_css_is_analysis_only() -> None:
    css = CompanionApp.CSS
    assert "#dashboard-monitor" in css
    assert "#dashboard-capture" in css
    assert "#dashboard-checkpoints" in css
    assert "#dashboard-task" not in css
    assert "#dashboard-goals" not in css
    assert ".goal-box" not in css


def test_swarm_css_includes_two_panel_layout() -> None:
    css = CompanionApp.CSS
    assert "#swarm-body" in css
    assert "#swarm-agents" in css
    assert "#swarm-detail" in css


def test_next_body_mode_cycles_through_dashboard_diff_files_swarm() -> None:
    assert next_body_mode("dashboard-body") == "diff-body"
    assert next_body_mode("diff-body") == "files-body"
    assert next_body_mode("files-body") == "swarm-body"
    assert next_body_mode("swarm-body") == "dashboard-body"
