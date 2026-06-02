"""Textual app shell for the basecamp companion dashboard."""

from __future__ import annotations

from pathlib import Path

from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.util import ClassNotFound
from rich.syntax import Syntax
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Label, ListItem, ListView, Static

from basecamp.companion.diff import DiffLine, FileStatus, collect_changes, file_diff_lines, make_git_runner
from basecamp.companion.snapshot import CompanionSnapshot, load_snapshot, render_state_lines


class StatePanel(Static):
    """Top state panel with session summary."""

    def update_snapshot(self, snapshot: CompanionSnapshot | None) -> None:
        """Update rendered state panel content from a snapshot."""

        self.update("\n".join(render_state_lines(snapshot)))


class FileList(Vertical):
    """Navigable list of changed files."""

    class SelectionChanged(Message):
        """Posted when the highlighted file changes."""

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
        yield ListView(id="file-list-list")

    @property
    def selected_file(self) -> FileStatus | None:
        """Return the currently highlighted file entry."""

        list_view = self.query_one("#file-list-list", ListView)
        if list_view.index is None:
            return None
        if list_view.index < 0 or list_view.index >= len(self._files):
            return None
        return self._files[list_view.index]

    def _glyph_for(self, status: FileStatus) -> str:
        glyph_map = {
            "added": "A",
            "modified": "M",
            "deleted": "D",
            "renamed": "R",
        }
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
        empty = self.query_one("#file-list-empty", Static)
        list_view = self.query_one("#file-list-list", ListView)
        empty.display = False
        list_view.display = True

    def update_changes(self, base_commit: str | None, files: list[FileStatus]) -> None:
        """Rebuild file list while preserving selection by path."""

        previous_path = self.selected_file.path if self.selected_file else self._selected_path
        self._base_commit = base_commit
        self._files = list(files)

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

    def on_list_view_highlighted(self, _: ListView.Highlighted) -> None:
        """Publish selected file changes for immediate diff refresh."""

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
        try:
            lexer = get_lexer_for_filename(file_path)
        except ClassNotFound:
            lexer = TextLexer()

        syntax = Syntax(code="", lexer=lexer, line_numbers=False, word_wrap=False)
        line_number_width = max(1, len(str(max((line.line_no or 0) for line in diff_lines) or 1)))

        color_map = {
            "added": "on #12301b",
            "removed": "on #3a1a1a",
            "context": "",
        }
        marker_map = {
            "added": "+",
            "removed": "-",
            "context": " ",
        }

        rendered = Text()
        for line in diff_lines:
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


class CompanionApp(App[None]):
    """Companion dashboard app."""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("tab", "focus_next", "Next Pane"),
        ("shift+tab", "focus_previous", "Prev Pane"),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }

    #state-panel {
        border: round $accent;
        height: auto;
        padding: 0 1;
    }

    #file-list {
        border: round $primary;
        height: 10;
        padding: 0 1;
    }

    #file-list-list {
        height: 1fr;
    }

    #diff-view {
        border: round $secondary;
        height: 1fr;
        min-height: 5;
        padding: 0 1;
    }

    #diff-content {
        width: 100%;
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

    def compose(self) -> ComposeResult:
        """Compose dashboard widgets."""

        yield StatePanel(id="state-panel")
        yield FileList(id="file-list")
        yield DiffView(id="diff-view")

    def on_mount(self) -> None:
        """Initial load and refresh timer."""

        self._refresh()
        self.set_interval(1.0, self._refresh)
        self.query_one("#file-list-list", ListView).focus()

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
            )
        except Exception:
            diff_view.update_diff(file_path=selected_file.path, status_message="Unable to load diff", diff_lines=[])
            return

        diff_view.update_diff(
            file_path=selected_file.path,
            status_message=status_message,
            diff_lines=diff_lines,
        )

    def _refresh(self) -> None:
        """Refresh state panel on snapshot changes and git views every tick."""

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
            self.query_one("#state-panel", StatePanel).update_snapshot(self._snapshot)

        try:
            base_commit, files = collect_changes(self._git)
        except Exception:
            base_commit, files = None, []

        if base_commit != self._base_commit or files != self._files:
            self._base_commit = base_commit
            self._files = files
            self.query_one("#file-list", FileList).update_changes(base_commit=base_commit, files=files)

        self._update_selected_file_diff()


def run_companion(snapshot_path: Path, cwd: Path) -> None:
    """Run the companion dashboard app."""

    app = CompanionApp(snapshot_path=snapshot_path, cwd=cwd)
    app.run()
