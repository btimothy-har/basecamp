"""Textual app shell for the Basecamp companion TUI."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import ContentSwitcher, Footer, Static

from basecamp.companion.daemon import (
    DaemonAgentMessages,
    DaemonSummary,
    DaemonSummarySource,
)
from basecamp.companion.delta_render import render_file_diff
from basecamp.companion.diff import (
    DIFF_DENSITIES,
    DIFF_LAYOUTS,
    DIFF_SCOPES,
    DiffDensity,
    DiffLayout,
    DiffScope,
    FileStatus,
    collapse_unchanged,
    collect_changes,
    file_diff_lines,
    git_status_summary,
    make_git_runner,
    resolve_browse_roots,
)
from basecamp.companion.poll import apply_effective_cwd, poll_daemon_messages, poll_daemon_summary
from basecamp.companion.snapshot import CompanionSnapshot, load_snapshot
from basecamp.companion.ui.diff import DiffBody, DiffView, FileList
from basecamp.companion.ui.files import FileBrowser
from basecamp.companion.ui.modes import next_body_mode
from basecamp.companion.ui.swarm import SwarmBody
from basecamp.companion.ui.workspace import WorkspacePanel, _MenuOrderedScreen


class CompanionApp(App[None]):
    """Live session companion."""

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

    #swarm-body {
        height: 1fr;
        padding: 0 1;
    }

    #swarm-layout {
        height: 1fr;
        layout: horizontal;
    }

    .swarm-box {
        border: round $accent;
        padding: 0 1;
    }

    #swarm-agents {
        height: 1fr;
        width: 34%;
        margin-right: 1;
    }

    #swarm-detail {
        height: 1fr;
        width: 1fr;
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
        layout: horizontal;
    }

    #session-bar-mode {
        width: auto;
    }

    #session-bar-meta {
        width: 1fr;
        text-align: right;
    }
    """

    def __init__(
        self,
        snapshot_path: Path,
        cwd: Path,
        scratch_dir: Path | None = None,
        daemon_source: DaemonSummarySource | None = None,
    ) -> None:
        super().__init__()
        self.snapshot_path = snapshot_path
        self.cwd = cwd
        self.scratch_dir = scratch_dir
        self._daemon_source = daemon_source or DaemonSummarySource()
        self._git = make_git_runner(cwd)
        self._snapshot_mtime_ns: int | None = None
        self._snapshot_exists: bool | None = None
        self._snapshot: CompanionSnapshot | None = None
        self._base_commit: str | None = None
        self._files: list[FileStatus] = []
        self._diff_scope: DiffScope = "all"
        self._diff_density: DiffDensity = "full"
        self._diff_layout: DiffLayout = "split"

    def compose(self) -> ComposeResult:
        """Compose companion widgets."""

        yield WorkspacePanel(id="workspace-panel")
        yield ContentSwitcher(
            DiffBody(id="diff-body"),
            FileBrowser(resolve_browse_roots(self._git, self.cwd, self.scratch_dir), id="files-body"),
            SwarmBody(id="swarm-body"),
            id="body",
            initial="diff-body",
        )
        with Horizontal(id="session-bar"):
            yield Static(id="session-bar-mode")
            yield Static(id="session-bar-meta")
        yield Footer()

    def on_mount(self) -> None:
        """Initial load and refresh timer."""

        self._set_diff_title()
        self._update_session_bar()
        self._refresh()
        self._update_mode_indicator()
        self.set_interval(1.0, self._refresh)
        self.query_one("#diff-view", DiffView).focus()

    def _set_diff_title(self) -> None:
        parts = ["Diff", self._diff_scope, self._diff_density, self._diff_layout]
        self.query_one("#diff-view", DiffView).border_title = " · ".join(parts)

    def _update_session_bar(self) -> None:
        title = self._snapshot.title if self._snapshot else None
        short_session_id = self._snapshot.session_id.replace("-", "")[-6:] if self._snapshot else None
        parts = [part for part in (title, f"⬡ {short_session_id}" if short_session_id else None) if part]
        self.query_one("#session-bar-meta", Static).update(f"[dim]{'  ·  '.join(parts)}[/dim]")

    def _update_mode_indicator(self) -> None:
        current = self.query_one("#body", ContentSwitcher).current
        labels = {
            "diff-body": "Diff",
            "files-body": "Files",
            "swarm-body": "Swarm",
        }
        self.query_one("#session-bar-mode", Static).update(f"[dim]{labels.get(current, 'Diff')}[/dim]")

    def action_prev_file(self) -> None:
        """Move file selection to the previous changed file."""

        self.query_one("#file-list", FileList).select_prev()

    def action_next_file(self) -> None:
        """Move file selection to the next changed file."""

        self.query_one("#file-list", FileList).select_next()

    def action_toggle_diff_density(self) -> None:
        """Toggle full or compact context for the active diff."""

        index = DIFF_DENSITIES.index(self._diff_density)
        self._diff_density = DIFF_DENSITIES[(index + 1) % len(DIFF_DENSITIES)]
        self._set_diff_title()
        self._update_selected_file_diff()

    def action_toggle_diff_layout(self) -> None:
        """Toggle stacked or split rendering for the active diff."""

        index = DIFF_LAYOUTS.index(self._diff_layout)
        self._diff_layout = DIFF_LAYOUTS[(index + 1) % len(DIFF_LAYOUTS)]
        self._set_diff_title()
        self._update_selected_file_diff()

    def action_cycle_diff_scope(self) -> None:
        """Cycle the diff scope between all, uncommitted, and committed."""

        index = DIFF_SCOPES.index(self._diff_scope)
        self._diff_scope = DIFF_SCOPES[(index + 1) % len(DIFF_SCOPES)]
        self._set_diff_title()
        self._refresh()

    def action_toggle_mode(self) -> None:
        """Cycle body modes, focusing the active pane."""

        switcher = self.query_one("#body", ContentSwitcher)
        switcher.current = next_body_mode(switcher.current)

        if switcher.current == "diff-body":
            self.query_one("#diff-view", DiffView).focus()
        elif switcher.current == "files-body":
            self.query_one("#files-body", FileBrowser).focus_tree()
        elif switcher.current == "swarm-body":
            self.query_one("#swarm-body", SwarmBody).focus()

        self._update_mode_indicator()

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
                scope=self._diff_scope,
            )
        except Exception:
            diff_view.update_diff(file_path=selected_file.path, status_message="Unable to load diff", diff_lines=[])
            return

        if self._diff_density == "compact" and not status_message and diff_lines:
            diff_lines = collapse_unchanged(diff_lines)

        delta_factory = None
        if not status_message and diff_lines:

            def delta_factory(width: int, _file: FileStatus = selected_file) -> Text | None:
                return render_file_diff(
                    cwd=self.cwd,
                    base_commit=self._base_commit,
                    file=_file,
                    scope=self._diff_scope,
                    density=self._diff_density,
                    layout=self._diff_layout,
                    width=width,
                )

        diff_view.update_diff(
            file_path=selected_file.path,
            status_message=status_message,
            diff_lines=diff_lines,
            render_key=(self._diff_density, self._diff_layout),
            delta_factory=delta_factory,
        )

    def _apply_effective_cwd(self, snapshot: CompanionSnapshot) -> bool:
        """Switch git/file state to the snapshot cwd when it changes."""

        return apply_effective_cwd(self, snapshot)

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

        cwd_changed = snapshot_changed and self._snapshot is not None and self._apply_effective_cwd(self._snapshot)

        swarm_body = self.query_one("#swarm-body", SwarmBody)

        if self._snapshot is not None:
            swarm_body.update_daemon(self._poll_daemon_summary(self._snapshot.session_id))
            agent_handle = swarm_body.selected_agent_handle()
            if agent_handle is None:
                swarm_body.update_agent_messages(None)
            else:
                swarm_body.update_agent_messages(self._poll_daemon_messages(self._snapshot.session_id, agent_handle))
        else:
            swarm_body.update_daemon(None)
            swarm_body.update_agent_messages(None)

        try:
            base_commit, files = collect_changes(self._git, self._diff_scope)
        except Exception:
            base_commit, files = None, []

        if cwd_changed or base_commit != self._base_commit or files != self._files:
            self._base_commit = base_commit
            self._files = files
            self.query_one("#file-list", FileList).update_changes(base_commit=base_commit, files=files)

        try:
            status = git_status_summary(self._git, base_commit, len(files))
        except Exception:
            status = None
        self.query_one("#workspace-panel", WorkspacePanel).update_workspace(self._snapshot, status)

        self._update_selected_file_diff()

    def _poll_daemon_summary(self, root_id: str) -> DaemonSummary:
        return poll_daemon_summary(self, root_id)

    def _poll_daemon_messages(self, root_id: str, agent_handle: str) -> DaemonAgentMessages:
        return poll_daemon_messages(self, root_id, agent_handle)


def run_companion(snapshot_path: Path, cwd: Path, scratch_dir: Path | None = None) -> None:
    """Run the companion TUI."""

    app = CompanionApp(snapshot_path=snapshot_path, cwd=cwd, scratch_dir=scratch_dir)
    app.run()
