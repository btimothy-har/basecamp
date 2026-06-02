"""Textual app shell for the basecamp companion dashboard."""

from __future__ import annotations

from pathlib import Path

from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.util import ClassNotFound
from rich.syntax import Syntax
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static

from basecamp.companion.diff import (
    DiffLine,
    FileStatus,
    collapse_unchanged,
    collect_changes,
    file_diff_lines,
    make_git_runner,
)
from basecamp.companion.snapshot import CompanionSnapshot, load_snapshot, render_state_lines


class StatePanel(Static):
    """Top state panel with session summary."""

    def update_snapshot(self, snapshot: CompanionSnapshot | None) -> None:
        """Update rendered state panel content from a snapshot."""

        self.update("\n".join(render_state_lines(snapshot)))


class FileBar(Static):
    """Compact changed-file selector bar."""

    RENAMED_FROM_MAX = 32

    class SelectionChanged(Message):
        """Posted when the selected file changes."""

        def __init__(self, file_status: FileStatus | None) -> None:
            super().__init__()
            self.file_status = file_status

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._files: list[FileStatus] = []
        self._index = 0
        self._base_commit: str | None = None
        self._compact = False

    @property
    def selected_file(self) -> FileStatus | None:
        """Return the currently selected file, if any."""

        if self._index < 0 or self._index >= len(self._files):
            return None
        return self._files[self._index]

    def set_compact(self, *, compact: bool) -> None:
        """Update compact/full mode indicator."""

        if compact == self._compact:
            return

        self._compact = compact
        self._refresh_display()

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
        if status.status == "renamed" and status.old_path and len(status.old_path) <= self.RENAMED_FROM_MAX:
            return f"{glyph} {status.path} (from {status.old_path})"
        return f"{glyph} {status.path}"

    def _mode_label(self) -> str:
        return "COMPACT" if self._compact else "FULL"

    def _refresh_display(self) -> None:
        if self._base_commit is None:
            body = "Not a git repository"
        elif not self._files:
            body = f"No changes vs {self._base_commit[:7]}"
        else:
            selected = self._files[self._index]
            body = f"‹ {self._label_for(selected)} ({self._index + 1}/{len(self._files)}) ›"

        self.update(f"{body} · {self._mode_label()}")

    def update_changes(self, base_commit: str | None, files: list[FileStatus]) -> None:
        """Refresh changed files while preserving selection by path when possible."""

        previous_index = self._index
        previous_path = self.selected_file.path if self.selected_file is not None else None

        self._base_commit = base_commit
        self._files = list(files)

        if base_commit is None or not self._files:
            self._index = 0
            self._refresh_display()
            self.post_message(self.SelectionChanged(None))
            return

        if previous_path is not None:
            for index, file_status in enumerate(self._files):
                if file_status.path == previous_path:
                    self._index = index
                    break
            else:
                self._index = min(previous_index, len(self._files) - 1)
        else:
            self._index = min(previous_index, len(self._files) - 1)

        self._refresh_display()
        self.post_message(self.SelectionChanged(self.selected_file))

    def select_next(self) -> None:
        """Select the next file (wrap-around)."""

        if len(self._files) < 2:
            return

        self._index = (self._index + 1) % len(self._files)
        self._refresh_display()
        self.post_message(self.SelectionChanged(self.selected_file))

    def select_prev(self) -> None:
        """Select the previous file (wrap-around)."""

        if len(self._files) < 2:
            return

        self._index = (self._index - 1) % len(self._files)
        self._refresh_display()
        self.post_message(self.SelectionChanged(self.selected_file))


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
            "gap": "",
        }
        marker_map = {
            "added": "+",
            "removed": "-",
            "context": " ",
            "gap": "⋯",
        }

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


class CompanionApp(App[None]):
    """Companion dashboard app."""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("left", "prev_file", "Prev file", priority=True),
        Binding("right", "next_file", "Next file", priority=True),
        Binding("c", "toggle_compact", "Compact", priority=True),
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

    #file-bar {
        border: round $primary;
        height: auto;
        padding: 0 1;
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

    def compose(self) -> ComposeResult:
        """Compose dashboard widgets."""

        yield StatePanel(id="state-panel")
        yield DiffView(id="diff-view")
        yield FileBar(id="file-bar")

    def on_mount(self) -> None:
        """Initial load and refresh timer."""

        self._refresh()
        self.set_interval(1.0, self._refresh)
        self.query_one("#diff-view", DiffView).focus()

    def action_prev_file(self) -> None:
        """Move file selection to the previous changed file."""

        self.query_one("#file-bar", FileBar).select_prev()

    def action_next_file(self) -> None:
        """Move file selection to the next changed file."""

        self.query_one("#file-bar", FileBar).select_next()

    def action_toggle_compact(self) -> None:
        """Toggle compact unchanged-line collapsing for the active diff."""

        self._compact = not self._compact
        self.query_one("#file-bar", FileBar).set_compact(compact=self._compact)
        self._update_selected_file_diff()

    def on_file_bar_selection_changed(self, _: FileBar.SelectionChanged) -> None:
        """Update diff immediately when file selection changes."""

        self._update_selected_file_diff()

    def _update_selected_file_diff(self) -> None:
        """Render selected file diff, handling empty/error states."""

        file_bar = self.query_one("#file-bar", FileBar)
        diff_view = self.query_one("#diff-view", DiffView)

        if self._base_commit is None:
            diff_view.update_diff(file_path="", status_message="Not a git repository", diff_lines=[])
            return

        selected_file = file_bar.selected_file
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

        if self._compact and not status_message and diff_lines:
            diff_lines = collapse_unchanged(diff_lines)

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
            self.query_one("#file-bar", FileBar).update_changes(base_commit=base_commit, files=files)

        self._update_selected_file_diff()


def run_companion(snapshot_path: Path, cwd: Path) -> None:
    """Run the companion dashboard app."""

    app = CompanionApp(snapshot_path=snapshot_path, cwd=cwd)
    app.run()
