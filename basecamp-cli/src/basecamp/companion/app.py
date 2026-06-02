"""Textual app shell for the basecamp companion dashboard."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

from pygments.lexer import Lexer
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.util import ClassNotFound
from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import ActiveBinding, Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import Screen
from textual.widgets import ContentSwitcher, DirectoryTree, Footer, Label, ListItem, ListView, Static
from textual.widgets.tree import TreeNode

from basecamp.companion.diff import (
    DIFF_MODES,
    DiffLine,
    DiffMode,
    FileStatus,
    WorkspaceStatus,
    collapse_unchanged,
    collect_changes,
    file_diff_lines,
    git_status_summary,
    make_git_runner,
    read_text_for_preview,
    resolve_browse_roots,
)
from basecamp.companion.snapshot import CompanionSnapshot, collapse_home, load_snapshot, render_workspace_lines


def lexer_for_filename(file_path: str) -> Lexer:
    """Return the best lexer for a filename, falling back to plain text."""

    try:
        return get_lexer_for_filename(file_path)
    except ClassNotFound:
        return TextLexer()


class WorkspacePanel(Static):
    """Top panel summarizing the workspace and git status."""

    def update_workspace(self, snapshot: CompanionSnapshot | None, status: WorkspaceStatus | None) -> None:
        """Update rendered workspace content."""

        self.update("\n".join(render_workspace_lines(snapshot, status)))


class FileList(Vertical):
    """Scrollable list of changed files."""

    class SelectionChanged(Message):
        """Posted when the selected file changes."""

        def __init__(self, file_status: FileStatus | None) -> None:
            super().__init__()
            self.file_status = file_status

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._files: list[FileStatus] = []
        self._selected_path: str | None = None
        self._base_commit: str | None = None

    def compose(self) -> ComposeResult:
        """Compose empty-state and list widgets."""

        yield Static(id="file-list-empty")
        # Display-only: navigation happens in the diff pane via ←/→.
        list_view = ListView(id="file-list-list")
        list_view.can_focus = False
        yield list_view

    @property
    def selected_file(self) -> FileStatus | None:
        """Return the currently highlighted file entry."""

        list_view = self.query_one("#file-list-list", ListView)
        index = list_view.index
        if index is None or index < 0 or index >= len(self._files):
            return None
        return self._files[index]

    def _glyph_for(self, status: FileStatus) -> str:
        glyph_map = {"added": "A", "modified": "M", "deleted": "D", "renamed": "R"}
        return glyph_map[status.status]

    def _label_for(self, status: FileStatus) -> str:
        glyph = self._glyph_for(status)
        if status.status == "renamed" and status.old_path:
            return f"{glyph} {status.path} (from {status.old_path})"
        return f"{glyph} {status.path}"

    def _set_empty_state(self, message: str) -> None:
        empty = self.query_one("#file-list-empty", Static)
        list_view = self.query_one("#file-list-list", ListView)
        empty.display = True
        empty.update(message)
        list_view.display = False

    def _set_list_state(self) -> None:
        self.query_one("#file-list-empty", Static).display = False
        self.query_one("#file-list-list", ListView).display = True

    def update_changes(self, base_commit: str | None, files: list[FileStatus]) -> None:
        """Rebuild the list while preserving selection by path."""

        previous_path = self.selected_file.path if self.selected_file else self._selected_path
        self._base_commit = base_commit
        self._files = list(files)
        self.border_title = f"Changed files ({len(files)})"

        list_view = self.query_one("#file-list-list", ListView)
        list_view.clear()

        if base_commit is None:
            self._selected_path = None
            self._set_empty_state("Not a git repository")
            self.post_message(self.SelectionChanged(None))
            return

        if not files:
            self._selected_path = None
            self._set_empty_state(f"No changes vs {base_commit[:7]}")
            self.post_message(self.SelectionChanged(None))
            return

        self._set_list_state()
        for file_status in files:
            list_view.append(ListItem(Label(self._label_for(file_status))))

        selected_index = 0
        if previous_path is not None:
            for index, file_status in enumerate(files):
                if file_status.path == previous_path:
                    selected_index = index
                    break

        list_view.index = selected_index
        self._selected_path = files[selected_index].path
        self.post_message(self.SelectionChanged(self.selected_file))

    def select_next(self) -> None:
        """Select the next file (wrap-around)."""

        if len(self._files) < 2:
            return
        list_view = self.query_one("#file-list-list", ListView)
        current = list_view.index or 0
        list_view.index = (current + 1) % len(self._files)

    def select_prev(self) -> None:
        """Select the previous file (wrap-around)."""

        if len(self._files) < 2:
            return
        list_view = self.query_one("#file-list-list", ListView)
        current = list_view.index or 0
        list_view.index = (current - 1) % len(self._files)

    def on_list_view_highlighted(self, _: ListView.Highlighted) -> None:
        """Publish selection changes for immediate diff refresh."""

        selected_file = self.selected_file
        self._selected_path = selected_file.path if selected_file else None
        self.post_message(self.SelectionChanged(selected_file))


class DiffView(VerticalScroll):
    """Scrollable full-file diff renderer."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._last_signature: tuple[str, str, tuple[tuple[str, str, int | None], ...]] | None = None

    def compose(self) -> ComposeResult:
        """Compose content holder."""

        yield Static(id="diff-content")

    def _signature(
        self,
        file_path: str,
        status_message: str,
        diff_lines: list[DiffLine],
    ) -> tuple[str, str, tuple[tuple[str, str, int | None], ...]]:
        return (
            file_path,
            status_message,
            tuple((line.kind, line.text, line.line_no) for line in diff_lines),
        )

    def _render_diff(self, file_path: str, diff_lines: list[DiffLine]) -> Text:
        syntax = Syntax(code="", lexer=lexer_for_filename(file_path), line_numbers=False, word_wrap=False)
        line_number_width = max(1, len(str(max((line.line_no or 0) for line in diff_lines) or 1)))

        color_map = {"added": "on #12301b", "removed": "on #3a1a1a", "context": "", "gap": ""}
        marker_map = {"added": "+", "removed": "-", "context": " ", "gap": "⋯"}

        rendered = Text()
        for line in diff_lines:
            if line.kind == "gap":
                gutter = f"{marker_map['gap']} {'':>{line_number_width}} "
                rendered.append(gutter, style="dim italic")
                rendered.append(line.text, style="dim italic")
                rendered.append("\n", style="dim italic")
                continue

            marker = marker_map[line.kind]
            number = "" if line.line_no is None else str(line.line_no)
            gutter = f"{marker} {number:>{line_number_width}} "
            row_style = color_map[line.kind]

            highlighted_line = syntax.highlight(line.text)
            highlighted_line.rstrip()
            if row_style:
                highlighted_line.stylize(row_style)
                rendered.append(gutter, style=row_style)
                rendered.append_text(highlighted_line)
                rendered.append("\n", style=row_style)
            else:
                rendered.append(gutter)
                rendered.append_text(highlighted_line)
                rendered.append("\n")

        if not diff_lines:
            rendered.append("(empty file)")

        return rendered

    def update_diff(self, file_path: str, status_message: str, diff_lines: list[DiffLine]) -> None:
        """Update diff rendering when content has changed."""

        signature = self._signature(file_path=file_path, status_message=status_message, diff_lines=diff_lines)
        if signature == self._last_signature:
            return

        content = self.query_one("#diff-content", Static)
        if status_message:
            content.update(status_message)
        else:
            content.update(self._render_diff(file_path=file_path, diff_lines=diff_lines))

        self._last_signature = signature


class DiffBody(Vertical):
    """Diff modality body containing the diff renderer and file list."""

    BINDINGS = [
        Binding("m", "app.toggle_mode", "Mode", priority=True),
        Binding("left", "prev_file", "Prev file", priority=True),
        Binding("right", "next_file", "Next file", priority=True),
        Binding("c", "toggle_compact", "Compact", priority=True),
        Binding("d", "cycle_diff_mode", "Diff scope", priority=True),
    ]

    def compose(self) -> ComposeResult:
        """Compose diff modality widgets."""

        yield DiffView(id="diff-view")
        yield FileList(id="file-list")

    def action_prev_file(self) -> None:
        self.app.action_prev_file()

    def action_next_file(self) -> None:
        self.app.action_next_file()

    def action_toggle_compact(self) -> None:
        self.app.action_toggle_compact()

    def action_cycle_diff_mode(self) -> None:
        self.app.action_cycle_diff_mode()


class _CompanionDirectoryTree(DirectoryTree):
    """Directory tree that hides internal git metadata."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [path for path in paths if path.name != ".git"]

    def render_label(self, node: TreeNode[object], base_style: Style, style: Style) -> Text:
        if node.parent is None:
            node._label = Text(collapse_home(str(self.path)))
        return super().render_label(node, base_style, style)


class FileBrowser(Horizontal):
    """Files modality body containing a tree and syntax preview."""

    BINDINGS = [
        Binding("m", "app.toggle_mode", "Mode"),
        Binding("o", "open_in_editor", "Open"),
        Binding("r", "toggle_root", "Root"),
        Binding("escape", "focus_tree", "Back"),
    ]

    _placeholder = "Select a file to preview"

    def __init__(self, roots: list[Path], *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.roots = roots
        self._root_index = 0
        self._root = roots[0]

    def _tree_title(self) -> str:
        if len(self.roots) < 2:
            return "Files"
        return "Files · worktree" if self._root_index == 0 else "Files · main"

    def compose(self) -> ComposeResult:
        # Keep tree reloads manual to preserve expansion/selection during timer refresh.
        tree = _CompanionDirectoryTree(self._root, id="file-tree")
        tree.border_title = self._tree_title()
        yield tree

        with VerticalScroll(id="file-preview"):
            yield Static(self._placeholder, id="file-preview-content")

    def on_mount(self) -> None:
        self.query_one("#file-preview", VerticalScroll).border_title = "Preview"

    def set_root(self, path: Path) -> None:
        self._root = path
        for index, root in enumerate(self.roots):
            if root == path:
                self._root_index = index
                break

        tree = self.query_one("#file-tree", _CompanionDirectoryTree)
        tree.path = path
        tree.border_title = self._tree_title()

    def action_toggle_root(self) -> None:
        if len(self.roots) < 2:
            return

        next_index = (self._root_index + 1) % len(self.roots)
        self.set_root(self.roots[next_index])

    def _clear_preview(self) -> None:
        preview = self.query_one("#file-preview", VerticalScroll)
        preview.border_title = "Preview"
        self.query_one("#file-preview-content", Static).update(self._placeholder)

    def show_path(self, path: Path) -> None:
        preview = self.query_one("#file-preview", VerticalScroll)
        content = self.query_one("#file-preview-content", Static)

        if path.is_dir():
            self._clear_preview()
            return

        status_message, text = read_text_for_preview(path)
        preview.border_title = str(path)

        if status_message:
            content.update(status_message)
            return

        if text is None:
            self._clear_preview()
            return

        content.update(
            Syntax(
                text,
                lexer=lexer_for_filename(str(path)),
                line_numbers=True,
                word_wrap=False,
            )
        )

    def on_tree_node_highlighted(self, event: DirectoryTree.NodeHighlighted) -> None:
        data = getattr(event.node, "data", None)
        if data is None:
            return

        path = data.path
        if path.is_file():
            self.show_path(path)
            return

        if path.is_dir():
            self._clear_preview()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.show_path(event.path)
        self.query_one("#file-preview", VerticalScroll).focus()

    def on_directory_tree_directory_selected(self, _: DirectoryTree.DirectorySelected) -> None:
        self._clear_preview()

    def action_focus_tree(self) -> None:
        self.query_one("#file-tree", _CompanionDirectoryTree).focus()

    def action_open_in_editor(self) -> None:
        tree = self.query_one("#file-tree", _CompanionDirectoryTree)
        node = tree.cursor_node
        if node is None or node.data is None:
            return

        path = node.data.path
        code_path = shutil.which("code")
        if code_path is None:
            self.app.notify("VS Code (code) not found on PATH", severity="warning")
            return

        try:
            subprocess.Popen([code_path, str(path)])  # noqa: S603
        except OSError:
            return


class _MenuOrderedScreen(Screen):
    """Default screen that orders footer bindings as [global mode][local][quit]."""

    @property
    def active_bindings(self) -> dict[str, ActiveBinding]:
        def rank(active: ActiveBinding) -> int:
            action = active.binding.action
            if action.endswith("toggle_mode"):
                return 0
            if action == "quit":
                return 2
            return 1

        bindings = super().active_bindings
        return dict(sorted(bindings.items(), key=lambda item: rank(item[1])))


class CompanionApp(App[None]):
    """Companion dashboard app."""

    BINDINGS = [Binding("q", "quit", "Quit")]

    def get_default_screen(self) -> Screen:
        """Use the menu-ordered screen so the footer reads mode-first, quit-last."""

        return _MenuOrderedScreen()

    CSS = """
    Screen {
        layout: vertical;
    }

    #workspace-panel {
        border: round $accent;
        height: auto;
        padding: 0 1;
    }

    #diff-view {
        border: round $secondary;
        height: 1fr;
        min-height: 5;
        overflow-x: hidden;
        padding: 0 1;
    }

    #diff-content {
        width: 100%;
    }

    #file-list {
        border: round $primary;
        height: 7;
        padding: 0 1;
    }

    #file-list-list {
        height: 1fr;
    }

    #body {
        height: 1fr;
    }

    #diff-body {
        height: 1fr;
    }

    #files-body {
        height: 1fr;
        layout: horizontal;
    }

    #file-tree {
        border: round $primary;
        padding: 0 1;
        width: 40%;
    }

    #file-preview {
        border: round $secondary;
        padding: 0 1;
        width: 1fr;
    }

    #session-bar {
        height: 1;
        padding: 0 1;
        text-align: right;
    }
    """

    def __init__(self, snapshot_path: Path, cwd: Path) -> None:
        super().__init__()
        self.snapshot_path = snapshot_path
        self.cwd = cwd
        self._git = make_git_runner(cwd)
        self._snapshot_mtime_ns: int | None = None
        self._snapshot_exists: bool | None = None
        self._snapshot: CompanionSnapshot | None = None
        self._base_commit: str | None = None
        self._files: list[FileStatus] = []
        self._compact = False
        self._diff_mode: DiffMode = "all"

    def compose(self) -> ComposeResult:
        """Compose dashboard widgets."""

        yield WorkspacePanel(id="workspace-panel")
        yield ContentSwitcher(
            DiffBody(id="diff-body"),
            FileBrowser(resolve_browse_roots(self._git, self.cwd), id="files-body"),
            id="body",
            initial="diff-body",
        )
        yield Static(id="session-bar")
        yield Footer()

    def on_mount(self) -> None:
        """Initial load and refresh timer."""

        self._set_diff_title()
        self._update_session_bar()
        self._refresh()
        self.set_interval(1.0, self._refresh)
        self.query_one("#diff-view", DiffView).focus()

    def _set_diff_title(self) -> None:
        parts = ["Diff", self._diff_mode]
        if self._compact:
            parts.append("compact")
        self.query_one("#diff-view", DiffView).border_title = " · ".join(parts)

    def _update_session_bar(self) -> None:
        title = self._snapshot.title if self._snapshot else None
        short_session_id = self._snapshot.session_id.replace("-", "")[-6:] if self._snapshot else None
        parts = [part for part in (title, f"⬡ {short_session_id}" if short_session_id else None) if part]
        self.query_one("#session-bar", Static).update(f"[dim]{'  ·  '.join(parts)}[/dim]")

    def action_prev_file(self) -> None:
        """Move file selection to the previous changed file."""

        self.query_one("#file-list", FileList).select_prev()

    def action_next_file(self) -> None:
        """Move file selection to the next changed file."""

        self.query_one("#file-list", FileList).select_next()

    def action_toggle_compact(self) -> None:
        """Toggle compact unchanged-line collapsing for the active diff."""

        self._compact = not self._compact
        self._set_diff_title()
        self._update_selected_file_diff()

    def action_cycle_diff_mode(self) -> None:
        """Cycle the diff scope between all, uncommitted, and committed."""

        index = DIFF_MODES.index(self._diff_mode)
        self._diff_mode = DIFF_MODES[(index + 1) % len(DIFF_MODES)]
        self._set_diff_title()
        self._refresh()

    def action_toggle_mode(self) -> None:
        """Toggle between diff and files bodies, focusing the active pane."""

        switcher = self.query_one("#body", ContentSwitcher)
        if switcher.current == "diff-body":
            switcher.current = "files-body"
            self.query_one("#file-tree", _CompanionDirectoryTree).focus()
            return

        switcher.current = "diff-body"
        self.query_one("#diff-view", DiffView).focus()

    def on_file_list_selection_changed(self, _: FileList.SelectionChanged) -> None:
        """Update diff immediately when file selection changes."""

        self._update_selected_file_diff()

    def _update_selected_file_diff(self) -> None:
        """Render selected file diff, handling empty/error states."""

        file_list = self.query_one("#file-list", FileList)
        diff_view = self.query_one("#diff-view", DiffView)

        if self._base_commit is None:
            diff_view.update_diff(file_path="", status_message="Not a git repository", diff_lines=[])
            return

        selected_file = file_list.selected_file
        if selected_file is None:
            diff_view.update_diff(
                file_path="",
                status_message=f"No changes vs {self._base_commit[:7]}",
                diff_lines=[],
            )
            return

        try:
            status_message, diff_lines = file_diff_lines(
                git=self._git,
                base_commit=self._base_commit,
                file=selected_file,
                cwd=self.cwd,
                mode=self._diff_mode,
            )
        except Exception:
            diff_view.update_diff(file_path=selected_file.path, status_message="Unable to load diff", diff_lines=[])
            return

        if self._compact and not status_message and diff_lines:
            diff_lines = collapse_unchanged(diff_lines)

        diff_view.update_diff(file_path=selected_file.path, status_message=status_message, diff_lines=diff_lines)

    def _refresh(self) -> None:
        """Refresh state panel on snapshot changes and git views every tick."""

        # The 1s interval can fire during teardown; the app clears is_running
        # before unmounting widgets, so bail to avoid querying a gone DOM.
        if not self.is_running:
            return

        try:
            file_exists = self.snapshot_path.exists()
            snapshot_mtime_ns = self.snapshot_path.stat().st_mtime_ns if file_exists else None
        except OSError:
            file_exists = False
            snapshot_mtime_ns = None

        snapshot_changed = file_exists != self._snapshot_exists or snapshot_mtime_ns != self._snapshot_mtime_ns
        if snapshot_changed:
            self._snapshot_exists = file_exists
            self._snapshot_mtime_ns = snapshot_mtime_ns
            self._snapshot = load_snapshot(self.snapshot_path) if file_exists else None
            self._update_session_bar()

        try:
            base_commit, files = collect_changes(self._git, self._diff_mode)
        except Exception:
            base_commit, files = None, []

        if base_commit != self._base_commit or files != self._files:
            self._base_commit = base_commit
            self._files = files
            self.query_one("#file-list", FileList).update_changes(base_commit=base_commit, files=files)

        try:
            status = git_status_summary(self._git, base_commit, len(files))
        except Exception:
            status = None
        self.query_one("#workspace-panel", WorkspacePanel).update_workspace(self._snapshot, status)

        self._update_selected_file_diff()


def run_companion(snapshot_path: Path, cwd: Path) -> None:
    """Run the companion dashboard app."""

    app = CompanionApp(snapshot_path=snapshot_path, cwd=cwd)
    app.run()
