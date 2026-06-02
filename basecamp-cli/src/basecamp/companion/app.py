"""Textual app shell for the basecamp companion dashboard."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Static

from basecamp.companion.snapshot import CompanionSnapshot, load_snapshot, render_state_lines


class StatePanel(Static):
    """Top state panel with session summary."""

    def update_snapshot(self, snapshot: CompanionSnapshot | None) -> None:
        """Update rendered state panel content from a snapshot."""

        self.update("\n".join(render_state_lines(snapshot)))


class FileList(Static):
    """Placeholder file list widget."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__("(file list — coming soon)", *args, **kwargs)
        self.snapshot: CompanionSnapshot | None = None
        self.cwd: Path | None = None

    def update_snapshot(self, snapshot: CompanionSnapshot | None, cwd: Path) -> None:
        """Store latest snapshot/cwd for future file list rendering."""

        self.snapshot = snapshot
        self.cwd = cwd


class DiffView(Static):
    """Placeholder diff viewer widget."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__("(diff viewer — coming soon)", *args, **kwargs)
        self.snapshot: CompanionSnapshot | None = None
        self.cwd: Path | None = None

    def update_snapshot(self, snapshot: CompanionSnapshot | None, cwd: Path) -> None:
        """Store latest snapshot/cwd for future diff rendering."""

        self.snapshot = snapshot
        self.cwd = cwd


class CompanionApp(App[None]):
    """Companion dashboard app."""

    BINDINGS = [("q", "quit", "Quit")]

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

    #diff-view {
        border: round $secondary;
        height: 1fr;
        min-height: 5;
        padding: 0 1;
    }
    """

    def __init__(self, snapshot_path: Path, cwd: Path) -> None:
        super().__init__()
        self.snapshot_path = snapshot_path
        self.cwd = cwd
        self._snapshot_mtime_ns: int | None = None
        self._snapshot_exists: bool | None = None
        self._snapshot: CompanionSnapshot | None = None

    def compose(self) -> ComposeResult:
        """Compose dashboard widgets."""

        yield StatePanel(id="state-panel")
        yield FileList(id="file-list")
        yield DiffView(id="diff-view")

    def on_mount(self) -> None:
        """Initial load and refresh timer."""

        self._refresh()
        self.set_interval(1.0, self._refresh)

    def _refresh(self) -> None:
        """Refresh snapshot-backed widgets when the snapshot file changes."""

        try:
            file_exists = self.snapshot_path.exists()
            snapshot_mtime_ns = self.snapshot_path.stat().st_mtime_ns if file_exists else None
        except OSError:
            file_exists = False
            snapshot_mtime_ns = None

        if file_exists == self._snapshot_exists and snapshot_mtime_ns == self._snapshot_mtime_ns:
            return

        self._snapshot_exists = file_exists
        self._snapshot_mtime_ns = snapshot_mtime_ns
        self._snapshot = load_snapshot(self.snapshot_path) if file_exists else None

        state_panel = self.query_one("#state-panel", StatePanel)
        file_list = self.query_one("#file-list", FileList)
        diff_view = self.query_one("#diff-view", DiffView)

        state_panel.update_snapshot(self._snapshot)
        file_list.update_snapshot(self._snapshot, self.cwd)
        diff_view.update_snapshot(self._snapshot, self.cwd)


def run_companion(snapshot_path: Path, cwd: Path) -> None:
    """Run the companion dashboard app."""

    app = CompanionApp(snapshot_path=snapshot_path, cwd=cwd)
    app.run()
