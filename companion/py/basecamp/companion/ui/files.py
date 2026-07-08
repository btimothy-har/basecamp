"""File browser body and widgets for the companion TUI."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import DirectoryTree, Static
from textual.widgets.tree import TreeNode

from companion_tui.diff import read_text_for_preview
from companion_tui.snapshot import collapse_home
from companion_tui.ui.syntax import lexer_for_filename


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

    def __init__(self, roots: list[tuple[str, Path]], *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.roots = roots
        self._root_index = 0
        self._label, self._root = roots[0]

    def _tree_title(self) -> str:
        if len(self.roots) < 2:
            return "Files"
        return f"Files · {self._label}"

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
        for index, (label, root) in enumerate(self.roots):
            if root == path:
                self._root_index = index
                self._label = label
                break

        tree = self.query_one("#file-tree", _CompanionDirectoryTree)
        tree.path = path
        tree.border_title = self._tree_title()
        self._clear_preview()

    def replace_roots(self, roots: list[tuple[str, Path]]) -> None:
        """Replace browse roots and reset tree/preview state to the primary root."""

        if not roots:
            return

        self.roots = list(roots)
        self.set_root(self.roots[0][1])

    def action_toggle_root(self) -> None:
        if len(self.roots) < 2:
            return

        next_index = (self._root_index + 1) % len(self.roots)
        self.set_root(self.roots[next_index][1])

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

    def focus_tree(self) -> None:
        self.query_one("#file-tree", _CompanionDirectoryTree).focus()

    def action_focus_tree(self) -> None:
        self.focus_tree()

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
