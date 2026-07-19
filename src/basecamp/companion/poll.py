"""Dashboard data-source wiring and daemon polling for the companion app."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from basecamp.companion.analysis import CompanionAnalysis
from basecamp.companion.cycles import companion_tasks_path
from basecamp.companion.daemon import (
    DaemonAgentMessages,
    DaemonAgentMessagesError,
    DaemonSummary,
    DaemonSummaryError,
)
from basecamp.companion.diff import make_git_runner, resolve_browse_roots
from basecamp.companion.snapshot import CompanionSnapshot
from basecamp.companion.source import DashboardSource
from basecamp.companion.ui.diff import DiffView
from basecamp.companion.ui.files import FileBrowser

if TYPE_CHECKING:
    from basecamp.companion.app import CompanionApp


def ensure_dashboard_source(app: CompanionApp, session_id: str) -> DashboardSource:
    if app._dashboard_source is not None and app._dashboard_source_session_id == session_id:
        return app._dashboard_source

    tasks_path = companion_tasks_path(session_id, app._tasks_dir)
    app._dashboard_source = DashboardSource(tasks_path, lambda: poll_daemon_analysis(app, session_id))
    app._dashboard_source_session_id = session_id
    return app._dashboard_source


def apply_effective_cwd(app: CompanionApp, snapshot: CompanionSnapshot) -> bool:
    """Switch git/file state to the snapshot cwd when it changes."""

    effective_cwd = snapshot.effective_cwd.strip()
    if not effective_cwd:
        return False

    new_cwd = Path(effective_cwd).expanduser()
    if new_cwd == app.cwd:
        return False

    app.cwd = new_cwd
    app._git = make_git_runner(new_cwd)
    app._base_commit = None
    app._files = []

    app.query_one("#files-body", FileBrowser).replace_roots(resolve_browse_roots(app._git, app.cwd, app.scratch_dir))
    app.query_one("#diff-view", DiffView).update_diff(file_path="", status_message="", diff_lines=[])
    return True


def poll_daemon_analysis(app: CompanionApp, session_id: str) -> CompanionAnalysis | None:
    try:
        return app._daemon_source.poll_analysis(session_id)
    except Exception:  # noqa: BLE001
        return None


def poll_daemon_summary(app: CompanionApp, root_id: str) -> DaemonSummary:
    try:
        return app._daemon_source.poll(root_id)
    except Exception as error:  # noqa: BLE001
        return DaemonSummaryError(error=str(error))


def poll_daemon_messages(app: CompanionApp, root_id: str, agent_handle: str) -> DaemonAgentMessages:
    try:
        return app._daemon_source.poll_messages(root_id, agent_handle)
    except Exception as error:  # noqa: BLE001
        return DaemonAgentMessagesError(error=str(error))
