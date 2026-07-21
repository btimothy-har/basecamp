"""Smoke tests for the companion Textual app."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from textual.widgets import ContentSwitcher, DirectoryTree, Footer, ListView, Static

from basecamp.companion.app import CompanionApp
from basecamp.companion.delta_render import delta_path
from basecamp.companion.diff import DiffLine
from basecamp.companion.ui.diff import DiffBody, DiffView, FileList
from basecamp.companion.ui.swarm import SwarmBody
from basecamp.companion.ui.workspace import WorkspacePanel


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)  # noqa: S603


def _write_snapshot(path: Path, session_id: str, effective_cwd: Path | str = "") -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "sessionId": session_id,
                "title": "Smoke session title",
                "updatedAt": "2026-06-02T12:34:56Z",
                "goal": "Companion smoke",
                "progress": {"completed": 1, "total": 2},
                "agentMode": "work",
                "skillsUsed": ["python-development"],
                "effectiveCwd": str(effective_cwd),
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

            workspace_panel = app.query_one("#workspace-panel", WorkspacePanel)
            workspace_text = str(workspace_panel.render())
            assert "main" in workspace_text
            assert "Session" not in workspace_text

            # Textual Footer is restored; title + serial sit in the right-aligned bar above it.
            app.query_one(Footer)
            session_bar_text = str(app.query_one("#session-bar-meta", Static).render())
            assert "Smoke session title" in session_bar_text
            assert "7890ef" in session_bar_text

            # The file list is display-only (not focusable).
            assert app.query_one("#file-list-list", ListView).can_focus is False

            # Diff is the default pane.
            file_list = app.query_one("#file-list", FileList)
            selected_before = file_list.selected_file
            assert selected_before is not None
            assert selected_before.path == "a_large.py"

            diff_view = app.query_one("#diff-view", DiffView)
            full_signature = diff_view._last_signature
            assert full_signature is not None
            full_line_count = len(full_signature[3])

            await pilot.press("c")
            await pilot.pause(0.1)

            compact_signature = diff_view._last_signature
            assert compact_signature is not None
            compact_line_count = len(compact_signature[3])
            assert 0 < compact_line_count < full_line_count

            diff_content = app.query_one("#diff-content", Static)
            assert str(diff_content.render()).strip() != ""

            await pilot.press("right")
            await pilot.pause(0.1)

            selected_after = file_list.selected_file
            assert selected_after is not None
            assert selected_after.path != selected_before.path

            # `d` cycles the diff scope (reflected in the diff border title).
            await pilot.press("d")
            await pilot.pause(0.1)
            assert "uncommitted" in str(diff_view.border_title)

    asyncio.run(run_smoke())


def test_diff_view_renders_empty_file() -> None:
    assert "(empty file)" in DiffView()._render_diff("empty.py", []).plain


def test_diff_bindings_are_scoped_to_diff_body() -> None:
    diff_keys = {binding.key for binding in DiffBody.BINDINGS}
    app_keys = {binding.key for binding in CompanionApp.BINDINGS}

    assert {"left", "right", "c", "d"}.issubset(diff_keys)
    assert {"left", "right", "c", "d"}.isdisjoint(app_keys)


def test_default_mode_is_diff_and_focused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run_default_mode_test() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()

            body = app.query_one("#body", ContentSwitcher)
            diff_view = app.query_one("#diff-view", DiffView)

            assert body.current == "diff-body"
            assert diff_view.has_focus

    asyncio.run(run_default_mode_test())


def test_mode_indicator_tracks_active_mode(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run_mode_indicator_test() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.2)

            mode_bar = app.query_one("#session-bar-mode", Static)
            assert "Diff" in str(mode_bar.render())

            await pilot.press("m")
            await pilot.pause(0.05)
            assert "Files" in str(mode_bar.render())

            await pilot.press("m")
            await pilot.pause(0.05)
            assert "Swarm" in str(mode_bar.render())

            await pilot.press("m")
            await pilot.pause(0.05)
            assert "Diff" in str(mode_bar.render())

    asyncio.run(run_mode_indicator_test())


def test_mode_toggle_switches_body_and_focus(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run_modality_test() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.2)

            body = app.query_one("#body", ContentSwitcher)
            diff_view = app.query_one("#diff-view", DiffView)
            file_tree = app.query_one("#file-tree", DirectoryTree)
            swarm = app.query_one("#swarm-body", SwarmBody)

            assert body.current == "diff-body"
            assert diff_view.has_focus

            await pilot.press("m")
            await pilot.pause(0.05)

            assert body.current == "files-body"
            assert file_tree.has_focus

            await pilot.press("m")
            await pilot.pause(0.05)

            assert body.current == "swarm-body"
            assert swarm.has_focus

            await pilot.press("m")
            await pilot.pause(0.05)

            assert body.current == "diff-body"
            assert diff_view.has_focus

    asyncio.run(run_modality_test())


def test_footer_binding_order_by_mode(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    def visible_descriptions() -> list[str]:
        return [binding.binding.description for binding in app.screen.active_bindings.values() if binding.binding.show]

    async def run_footer_order_test() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.2)

            diff_descriptions = [
                description
                for description in visible_descriptions()
                if description in {"Mode", "Prev file", "Next file", "Compact", "Diff scope", "Quit"}
            ]
            assert diff_descriptions == ["Mode", "Prev file", "Next file", "Compact", "Diff scope", "Quit"]

            await pilot.press("m")
            await pilot.pause(0.05)

            files_descriptions = [
                description
                for description in visible_descriptions()
                if description in {"Mode", "Open", "Root", "Back", "Quit"}
            ]
            assert files_descriptions == ["Mode", "Open", "Root", "Back", "Quit"]

    asyncio.run(run_footer_order_test())


def test_refresh_does_not_disturb_file_tree_focus(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run_refresh_focus_test() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.2)

            # Switch from the default diff pane to files mode.
            await pilot.press("m")
            await pilot.pause(0.05)

            file_tree = app.query_one("#file-tree", DirectoryTree)
            assert file_tree.has_focus

            app._refresh()
            await pilot.pause(0.05)

            assert file_tree.has_focus

    asyncio.run(run_refresh_focus_test())


def test_refresh_is_noop_when_not_running(tmp_path: Path) -> None:
    """_refresh must not touch the DOM when the app isn't mounted (teardown race)."""

    app = CompanionApp(snapshot_path=tmp_path / "missing.json", cwd=tmp_path)
    assert app.is_running is False

    app._refresh()  # would raise NoMatches/ScreenStackError without the guard


def test_diff_pane_renders_through_delta_when_available(tmp_path: Path) -> None:
    """When delta is installed, the assembled app renders the diff via delta (styled Text)."""

    if delta_path() is None:
        pytest.skip("delta binary not installed")

    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.3)

            # b_small.txt is a small text change; navigate to it for a compact render.
            file_list = app.query_one("#file-list", FileList)
            for _ in range(6):
                if file_list.selected_file and file_list.selected_file.path == "b_small.txt":
                    break
                await pilot.press("right")
                await pilot.pause(0.1)

            content = str(app.query_one("#diff-content", Static).render())
            # delta renders side-by-side column separators (│) that the built-in
            # unified renderer never emits — proof the delta path produced this.
            assert "│" in content

    asyncio.run(run())


def test_diff_signature_tracks_width_for_delta_only() -> None:
    """A delta render's width is part of its signature so resize invalidates it."""

    view = DiffView()
    lines = [DiffLine(kind="added", text="x", line_no=1)]

    # With a delta render, differing widths yield differing signatures (resize
    # re-renders); without one, width is ignored (Rich reflows at display time).
    sig_w80 = view._signature("f.py", "", lines, width=80)
    sig_w120 = view._signature("f.py", "", lines, width=120)
    assert sig_w80 != sig_w120

    sig_fallback_a = view._signature("f.py", "", lines, width=None)
    sig_fallback_b = view._signature("f.py", "", lines, width=None)
    assert sig_fallback_a == sig_fallback_b
