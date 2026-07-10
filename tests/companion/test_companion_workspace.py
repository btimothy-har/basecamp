"""Tests for the companion workspace file browser and cwd tracking."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from rich.style import Style
from rich.syntax import Syntax
from test_companion_app import _build_repo, _write_snapshot
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import ContentSwitcher, DirectoryTree, Static

from basecamp.companion.app import CompanionApp
from basecamp.companion.snapshot import collapse_home
from basecamp.companion.ui import files as files_ui
from basecamp.companion.ui.files import FileBrowser


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
