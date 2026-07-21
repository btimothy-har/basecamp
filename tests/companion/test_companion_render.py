"""Rendering and body-mode tests for Companion."""

from __future__ import annotations

from basecamp.companion.app import CompanionApp
from basecamp.companion.ui.formatting import _format_duration, _truncate_preview
from basecamp.companion.ui.modes import next_body_mode


def test_truncate_preview_collapses_newlines_and_respects_limit() -> None:
    assert _truncate_preview("one\ntwo", max_length=20) == "one two"
    assert _truncate_preview("abcdef", max_length=4) == "abc…"


def test_format_duration_boundaries() -> None:
    assert _format_duration(59) == "59s"
    assert _format_duration(60) == "1m"
    assert _format_duration(3661) == "1h 1m"


def test_swarm_css_includes_two_panel_layout() -> None:
    css = CompanionApp.CSS
    assert "#swarm-body" in css
    assert "#swarm-agents" in css
    assert "#swarm-detail" in css


def test_next_body_mode_cycles_through_diff_files_swarm() -> None:
    assert next_body_mode("diff-body") == "files-body"
    assert next_body_mode("files-body") == "swarm-body"
    assert next_body_mode("swarm-body") == "diff-body"
