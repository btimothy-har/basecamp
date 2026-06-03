"""Tests for companion dashboard mode and analysis rendering."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from basecamp.companion.analysis import CompanionAnalysis
from basecamp.companion.app import CompanionApp, DashboardBody, _render_bullets, next_body_mode
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


def _write_snapshot(path: Path, session_id: str) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "sessionId": session_id,
                "title": "Dashboard session",
                "updatedAt": "2026-06-04T12:34:56Z",
            }
        ),
        encoding="utf-8",
    )


def test_render_bullets_empty_shows_dash() -> None:
    assert _render_bullets([]).plain == "—"


def test_render_bullets_populated() -> None:
    plain = _render_bullets(["first", "second"]).plain
    assert "• first" in plain
    assert "• second" in plain


def test_render_bullets_preserves_literal_markup_text() -> None:
    assert "[bold]x[/]" in _render_bullets(["[bold]x[/]"]).plain


def test_next_body_mode_cycles_three_way() -> None:
    assert next_body_mode("diff-body") == "files-body"
    assert next_body_mode("files-body") == "dashboard-body"
    assert next_body_mode("dashboard-body") == "diff-body"


def test_dashboard_mode_loads_sidecar_and_cycles(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")

    analysis_path = snapshot_path.parent / f"{snapshot_path.stem}.analysis.json"
    analysis_path.write_text(
        json.dumps(
            {
                "version": 1,
                "sessionId": "abcd-1234-5678-90ef",
                "updatedAt": "2026-06-04T12:35:00Z",
                "model": "test-model",
                "recap": ["dashboard recap"],
                "decisions": ["dashboard decision"],
                "openItems": ["dashboard open item"],
                "warnings": ["dashboard warning"],
            }
        ),
        encoding="utf-8",
    )

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run_dashboard_test() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.25)

            switcher = app.query_one("#body", ContentSwitcher)
            assert switcher.current == "files-body"

            await pilot.press("m")
            await pilot.pause(0.1)

            assert switcher.current == "dashboard-body"
            assert app.query_one("#dashboard-body", DashboardBody).has_focus

            for box_id in ("#dashboard-recap", "#dashboard-decisions", "#dashboard-open", "#dashboard-warnings"):
                app.query_one(box_id, Static)

    asyncio.run(run_dashboard_test())


def test_companion_analysis_round_trips_open_items() -> None:
    analysis = CompanionAnalysis(
        version=1,
        session_id="s",
        updated_at="2026-06-04T12:34:56Z",
        recap=["arc"],
        decisions=["chose boxes"],
        open_items=["widen window later"],
        warnings=["unverified claim"],
    )
    assert analysis.open_items == ["widen window later"]
    assert "openItems" in analysis.model_dump(by_alias=True)
