"""Workspace summary panel and menu-ordered default screen."""

from __future__ import annotations

from basecamp.companion.diff import WorkspaceStatus
from basecamp.companion.snapshot import CompanionSnapshot, render_workspace_lines
from textual.binding import ActiveBinding
from textual.screen import Screen
from textual.widgets import Static


class WorkspacePanel(Static):
    """Top panel summarizing the workspace and git status."""

    def update_workspace(self, snapshot: CompanionSnapshot | None, status: WorkspaceStatus | None) -> None:
        """Update rendered workspace content."""

        self.update("\n".join(render_workspace_lines(snapshot, status)))


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
