"""Smoke tests for the companion Textual app."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path

from companion_tui.app import CompanionApp, WorkspacePanel
from companion_tui.snapshot import collapse_home
from companion_tui.ui import files as files_ui
from companion_tui.ui.dashboard import DashboardBody
from companion_tui.ui.diff import DiffBody, DiffView, FileList
from companion_tui.ui.files import FileBrowser
from companion_tui.ui.swarm import SwarmBody
from rich.style import Style
from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import ContentSwitcher, DirectoryTree, Footer, ListView, Static


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
                "agentMode": "executor",
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

            # Dashboard is the default pane; one toggle reaches the diff view.
            await pilot.press("m")
            await pilot.pause(0.1)

            file_list = app.query_one("#file-list", FileList)
            selected_before = file_list.selected_file
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


def test_file_browser_preview_show_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")

    text_file = repo / "preview.py"
    text_file.write_text("print('hello')\n", encoding="utf-8")
    binary_file = repo / "preview.bin"
    binary_file.write_bytes(b"a\x00b")

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run_preview_test() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.2)

            body = app.query_one("#body", ContentSwitcher)
            body.current = "files-body"
            await pilot.pause(0.1)

            browser = app.query_one("#files-body", FileBrowser)
            tree = app.query_one("#file-tree", DirectoryTree)
            assert tree.path == repo

            browser.show_path(text_file)
            await pilot.pause(0.05)

            preview_content = app.query_one("#file-preview-content", Static)
            assert isinstance(preview_content.content, Syntax)
            assert "print('hello')" in preview_content.content.code

            browser.show_path(binary_file)
            await pilot.pause(0.05)
            assert preview_content.content == "Binary file — not shown"

    asyncio.run(run_preview_test())


def test_file_browser_highlight_updates_preview_live(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")

    (repo / "nav_target.py").write_text("print('navigated')\n", encoding="utf-8")

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run_highlight_test() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.2)

            tree = app.query_one("#file-tree", DirectoryTree)
            node = next(
                child
                for child in tree.root.children
                if child.data is not None and child.data.path.name == "nav_target.py"
            )
            tree.post_message(DirectoryTree.NodeHighlighted(node))
            await pilot.pause(0.1)

            preview_content = app.query_one("#file-preview-content", Static)
            assert isinstance(preview_content.content, Syntax)
            assert "print('navigated')" in preview_content.content.code

    asyncio.run(run_highlight_test())


def test_file_browser_selection_focuses_preview_then_escape_returns_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")

    (repo / "focus_target.py").write_text("print('focused')\n", encoding="utf-8")

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run_focus_drill_test() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.2)

            tree = app.query_one("#file-tree", DirectoryTree)
            node = next(
                child
                for child in tree.root.children
                if child.data is not None and child.data.path.name == "focus_target.py"
            )
            tree.post_message(DirectoryTree.FileSelected(node, node.data.path))
            await pilot.pause(0.1)

            preview = app.query_one("#file-preview", VerticalScroll)
            assert preview.has_focus

            await pilot.press("escape")
            await pilot.pause(0.05)
            assert tree.has_focus

    asyncio.run(run_focus_drill_test())


def test_diff_bindings_are_scoped_to_diff_body() -> None:
    diff_keys = {binding.key for binding in DiffBody.BINDINGS}
    app_keys = {binding.key for binding in CompanionApp.BINDINGS}

    assert {"left", "right", "c", "d"}.issubset(diff_keys)
    assert {"left", "right", "c", "d"}.isdisjoint(app_keys)


def test_default_mode_is_dashboard_and_focused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run_default_mode_test() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()

            body = app.query_one("#body", ContentSwitcher)
            dashboard = app.query_one("#dashboard-body", DashboardBody)

            assert body.current == "dashboard-body"
            assert dashboard.has_focus

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
            assert "Dashboard" in str(mode_bar.render())

            await pilot.press("m")
            await pilot.pause(0.05)
            assert "Diff" in str(mode_bar.render())

            await pilot.press("m")
            await pilot.pause(0.05)
            assert "Files" in str(mode_bar.render())

            await pilot.press("m")
            await pilot.pause(0.05)
            assert "Swarm" in str(mode_bar.render())

            await pilot.press("m")
            await pilot.pause(0.05)
            assert "Dashboard" in str(mode_bar.render())

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
            dashboard = app.query_one("#dashboard-body", DashboardBody)
            swarm = app.query_one("#swarm-body", SwarmBody)

            assert body.current == "dashboard-body"
            assert dashboard.has_focus

            await pilot.press("m")
            await pilot.pause(0.05)

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

            assert body.current == "dashboard-body"
            assert dashboard.has_focus

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

            dashboard_descriptions = [
                description for description in visible_descriptions() if description in {"Mode", "Quit"}
            ]
            assert dashboard_descriptions == ["Mode", "Quit"]

            await pilot.press("m")
            await pilot.pause(0.05)

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


def test_file_browser_open_in_editor(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")

    target = repo / "open_target.py"
    target.write_text("print('open')\n", encoding="utf-8")

    popen_calls: list[list[str]] = []

    def fake_popen(argv: list[str]) -> None:
        popen_calls.append(argv)
        return None

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run_open_test() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.2)

            tree = app.query_one("#file-tree", DirectoryTree)
            node = next(
                child
                for child in tree.root.children
                if child.data is not None and child.data.path.name == "open_target.py"
            )
            tree.move_cursor(node)

            monkeypatch.setattr(files_ui.shutil, "which", lambda _: "/fake/code")
            monkeypatch.setattr(files_ui.subprocess, "Popen", fake_popen)
            browser = app.query_one("#files-body", FileBrowser)
            browser.action_open_in_editor()

            assert popen_calls == [["/fake/code", str(target)]]

            monkeypatch.setattr(files_ui.shutil, "which", lambda _: None)
            browser.action_open_in_editor()
            assert popen_calls == [["/fake/code", str(target)]]

    asyncio.run(run_open_test())


def test_file_browser_root_toggle_two_roots(tmp_path: Path) -> None:
    worktree_root = tmp_path / "worktree"
    main_root = tmp_path / "main"
    worktree_root.mkdir()
    main_root.mkdir()
    (worktree_root / "only_worktree.txt").write_text("worktree\n", encoding="utf-8")
    (main_root / "only_main.txt").write_text("main\n", encoding="utf-8")

    browser = FileBrowser([("worktree", worktree_root), ("main", main_root)])

    class BrowserHarness(App[None]):
        def compose(self) -> ComposeResult:
            yield browser

    async def run_root_toggle_test() -> None:
        async with BrowserHarness().run_test() as pilot:
            await pilot.pause(0.1)

            tree = browser.query_one("#file-tree", DirectoryTree)
            content = browser.query_one("#file-preview-content", Static)
            assert tree.path == worktree_root
            assert tree.border_title == "Files · worktree"

            browser.show_path(worktree_root / "only_worktree.txt")
            await pilot.pause(0.05)
            assert content.content != browser._placeholder

            browser.action_toggle_root()
            await pilot.pause(0.05)
            assert tree.path == main_root
            assert tree.border_title == "Files · main"
            assert content.content == browser._placeholder

            browser.action_toggle_root()
            await pilot.pause(0.05)
            assert tree.path == worktree_root
            assert tree.border_title == "Files · worktree"

    asyncio.run(run_root_toggle_test())


def test_file_browser_root_toggle_single_root_noop(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "only.txt").write_text("file\n", encoding="utf-8")

    browser = FileBrowser([("worktree", root)])

    class BrowserHarness(App[None]):
        def compose(self) -> ComposeResult:
            yield browser

    async def run_single_root_test() -> None:
        async with BrowserHarness().run_test() as pilot:
            await pilot.pause(0.1)

            tree = browser.query_one("#file-tree", DirectoryTree)
            assert tree.path == root
            assert tree.border_title == "Files"

            browser.action_toggle_root()
            await pilot.pause(0.05)

            assert tree.path == root
            assert tree.border_title == "Files"

    asyncio.run(run_single_root_test())


def test_file_browser_three_roots_cycle_and_labels(tmp_path: Path) -> None:
    worktree_root = tmp_path / "worktree"
    main_root = tmp_path / "main"
    scratch_root = tmp_path / "scratch"
    worktree_root.mkdir()
    main_root.mkdir()
    scratch_root.mkdir()

    browser = FileBrowser(
        [
            ("worktree", worktree_root),
            ("main", main_root),
            ("scratch", scratch_root),
        ]
    )

    class BrowserHarness(App[None]):
        def compose(self) -> ComposeResult:
            yield browser

    async def run_three_root_cycle_test() -> None:
        async with BrowserHarness().run_test() as pilot:
            await pilot.pause(0.1)

            tree = browser.query_one("#file-tree", DirectoryTree)
            assert tree.path == worktree_root
            assert tree.border_title == "Files · worktree"

            browser.action_toggle_root()
            await pilot.pause(0.05)
            assert tree.path == main_root
            assert tree.border_title == "Files · main"

            browser.action_toggle_root()
            await pilot.pause(0.05)
            assert tree.path == scratch_root
            assert tree.border_title == "Files · scratch"

            browser.action_toggle_root()
            await pilot.pause(0.05)
            assert tree.path == worktree_root
            assert tree.border_title == "Files · worktree"

    asyncio.run(run_three_root_cycle_test())


def test_file_tree_root_label_collapses_home_path() -> None:
    with tempfile.TemporaryDirectory(prefix="basecamp-companion-", dir=Path.home()) as home_tmp:
        repo = Path(home_tmp) / "repo"
        snapshot_path = Path(home_tmp) / "snapshot.json"
        _build_repo(repo)
        _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")

        app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

        async def run_root_label_test() -> None:
            async with app.run_test() as pilot:
                await pilot.pause(0.2)

                await pilot.pause(0.1)

                tree = app.query_one("#file-tree", DirectoryTree)
                tree.render_label(tree.root, Style(), Style())
                root_label = tree.root._label.plain

                assert root_label.startswith("~")
                assert str(Path.home()) not in root_label
                assert collapse_home(str(tree.root.data.path)) == f"~/{repo.relative_to(Path.home())}"

        asyncio.run(run_root_label_test())


def test_refresh_does_not_disturb_file_tree_focus(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run_refresh_focus_test() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.2)

            # Dashboard is the default pane; switch to files mode to focus the tree.
            await pilot.press("m")
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


def _bump_mtime(path: Path) -> None:
    stat = path.stat()
    bumped = stat.st_mtime_ns + 1_000_000_000
    os.utime(path, ns=(bumped, bumped))


def test_refresh_follows_effective_cwd_change(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo_a)
    _build_repo(repo_b)
    (repo_b / "unique_b.txt").write_text("only in b\n", encoding="utf-8")
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef", effective_cwd=repo_a)

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo_a)

    async def run_cwd_change_test() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            assert app.cwd == repo_a

            _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef", effective_cwd=repo_b)
            _bump_mtime(snapshot_path)
            app._refresh()
            await pilot.pause(0.1)

            assert app.cwd == repo_b

            browser = app.query_one("#files-body", FileBrowser)
            assert browser.roots[0][1].resolve() == repo_b.resolve()

            tree = app.query_one("#file-tree", DirectoryTree)
            assert tree.path.resolve() == repo_b.resolve()

            changed_paths = {status.path for status in app._files}
            assert "unique_b.txt" in changed_paths

    asyncio.run(run_cwd_change_test())


def test_refresh_keeps_cwd_when_effective_cwd_empty(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef", effective_cwd=repo)

    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run_empty_cwd_test() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            assert app.cwd == repo

            _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef", effective_cwd="")
            _bump_mtime(snapshot_path)
            app._refresh()
            await pilot.pause(0.1)

            assert app.cwd == repo

    asyncio.run(run_empty_cwd_test())
