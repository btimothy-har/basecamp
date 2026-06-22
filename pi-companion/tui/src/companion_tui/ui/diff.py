"""Diff body and rendering widgets for the companion TUI."""

from __future__ import annotations

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Label, ListItem, ListView, Static

from companion_tui.diff import DiffLine, FileStatus
from companion_tui.ui.syntax import lexer_for_filename


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
