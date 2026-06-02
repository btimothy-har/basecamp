"""Smoke tests for the companion Textual app."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from basecamp.companion.app import CompanionApp, DiffView, FileBar
from textual.widgets import Static


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)  # noqa: S603


def _write_snapshot(path: Path, session_id: str) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "sessionId": session_id,
                "updatedAt": "2026-06-02T12:34:56Z",
                "goal": "Companion smoke",
                "progress": {"completed": 1, "total": 2},
                "agentMode": "executor",
                "skillsUsed": ["python-development"],
                "effectiveCwd": str(path.parent),
            }
        ),
        encoding="utf-8",
    )


def _build_repo(repo: Path) -> None:
    repo.mkdir()
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.email", "smoke@example.com")
    _run_git(repo, "config", "user.name", "Smoke Test")

    large_lines = [f"line {index}" for index in range(1, 301)]
    (repo / "a_large.py").write_text("\n".join(large_lines) + "\n", encoding="utf-8")
    (repo / "b_small.txt").write_text("small\n", encoding="utf-8")
    (repo / "c_keep.txt").write_text("keep\n", encoding="utf-8")

    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "base commit")

    large_lines[149] = "line 150 changed"
    (repo / "a_large.py").write_text("\n".join(large_lines) + "\n", encoding="utf-8")
    (repo / "b_small.txt").write_text("small\nchanged\n", encoding="utf-8")
    (repo / "d_new.txt").write_text("new\n", encoding="utf-8")


def test_companion_app_headless_smoke(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    session_id = "abcd-1234-5678-90ef"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id=session_id)

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run_smoke() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.3)

            state_panel = app.query_one("#state-panel", Static)
            assert "Session: 7890ef" in str(state_panel.render())

            file_bar = app.query_one("#file-bar", FileBar)
            bar_text = str(file_bar.render())
            assert "(1/3)" in bar_text
            assert "FULL" in bar_text

            selected_before = file_bar.selected_file
            assert selected_before is not None
            assert selected_before.path == "a_large.py"

            diff_view = app.query_one("#diff-view", DiffView)
            full_signature = diff_view._last_signature
            assert full_signature is not None
            full_line_count = len(full_signature[2])

            await pilot.press("c")
            await pilot.pause(0.1)

            compact_signature = diff_view._last_signature
            assert compact_signature is not None
            compact_line_count = len(compact_signature[2])
            assert compact_line_count < full_line_count

            assert compact_line_count > 0

            diff_content = app.query_one("#diff-content", Static)
            assert str(diff_content.render()).strip() != ""

            await pilot.press("right")
            await pilot.pause(0.1)

            selected_after = file_bar.selected_file
            assert selected_after is not None
            assert selected_after.path != selected_before.path

            assert "(2/3)" in str(file_bar.render())

    asyncio.run(run_smoke())
