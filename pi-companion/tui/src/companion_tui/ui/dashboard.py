"""Dashboard body and rendering helpers for the companion TUI."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from companion_tui.analysis import CompanionAnalysis
from companion_tui.snapshot import CompanionGoal
from companion_tui.source import DashboardModel
from companion_tui.ui.formatting import _STATUS_GLYPH


def _render_bullets(items: list[str]) -> Text:
    """Render items as markup-safe bullet lines, or an em dash when empty."""

    if not items:
        return Text("—", style="dim")

    rendered = Text()
    for index, item in enumerate(items):
        if index:
            rendered.append("\n")
        rendered.append("• ")
        rendered.append(item)
    return rendered


def _goal_panel(goal: CompanionGoal, is_selected: bool, is_active: bool) -> Panel:  # noqa: FBT001
    """Render a single goal as a bordered box; active is green, selection is yellow/bold."""

    border_style = "yellow" if is_selected else "green" if is_active else "grey42"
    return Panel(
        Text(goal.goal, style="bold" if is_selected else ""),
        title=Text("● active", style="green") if is_active else None,
        title_align="left",
        subtitle=f"{goal.progress.completed}/{goal.progress.total}",
        subtitle_align="right",
        border_style=border_style,
        padding=(0, 1),
    )


def _render_task_detail(goal: CompanionGoal | None, task_index: int) -> RenderableType:
    """Render the selected task header plus a faded annotation box, or an empty state."""

    if goal is None or not goal.tasks:
        return Text("No tasks", style="dim")

    index = max(0, min(task_index, len(goal.tasks) - 1))
    task = goal.tasks[index]
    header = Text()
    header.append(f"[{index + 1}/{len(goal.tasks)}] ", style="dim")
    header.append(f"{_STATUS_GLYPH.get(task.status, '•')} ")
    header.append(task.label, style="bold")
    if task.description:
        header.append("\n")
        header.append(task.description)

    if not task.notes:
        return header

    annotation = Panel(
        Text(task.notes, style="dim italic"),
        title=Text("✎ note", style="dim"),
        title_align="left",
        border_style="grey42",
        padding=(0, 1),
    )
    return Group(header, annotation)


class DashboardBody(Widget):
    """Goal-centric dashboard: chronological goals + task detail + inferred sections."""

    can_focus = True

    BINDINGS = [
        Binding("m", "app.toggle_mode", "Mode"),
        Binding("up", "goal_newer", "Newer goal"),
        Binding("down", "goal_older", "Older goal"),
        Binding("left", "task_prev", "Prev task"),
        Binding("right", "task_next", "Next task"),
    ]

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._goals: list[CompanionGoal] = []
        self._analysis: CompanionAnalysis | None = None
        self._selected_goal = 0
        self._selected_task = 0
        self._following = True
        self._active_index: int | None = None
        self._goal_widgets: list[Static] = []

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="dashboard-goals")
        with Vertical(id="dashboard-main"):
            yield Static(id="dashboard-task", classes="dashboard-box")
            yield Static(id="dashboard-decisions", classes="dashboard-box")
            with Horizontal(id="dashboard-bottom"):
                yield Static(id="dashboard-open", classes="dashboard-box")
                yield Static(id="dashboard-warnings", classes="dashboard-box")

    def render(self) -> Text:
        return Text()

    def on_mount(self) -> None:
        goals_panel = self.query_one("#dashboard-goals", VerticalScroll)
        goals_panel.border_title = "Goals"
        goals_panel.can_focus = False
        self.query_one("#dashboard-task", Static).border_title = "Task"
        self.query_one("#dashboard-decisions", Static).border_title = "Decisions"
        self.query_one("#dashboard-open", Static).border_title = "Open items"
        self.query_one("#dashboard-warnings", Static).border_title = "Warnings"
        self._render_dashboard()

    @staticmethod
    def _active_goal_index(goals: list[CompanionGoal]) -> int | None:
        for index, goal in enumerate(goals):
            if goal.active:
                return index
        return len(goals) - 1 if goals else None

    @staticmethod
    def _pinned_task_index(goal: CompanionGoal) -> int:
        """Pin to the active task, else the last task (e.g. when all are completed)."""
        for index, task in enumerate(goal.tasks):
            if task.status == "active":
                return index
        return max(0, len(goal.tasks) - 1)

    def _selected_goal_obj(self) -> CompanionGoal | None:
        return self._goals[self._selected_goal] if self._goals else None

    def update(self, model: DashboardModel) -> None:
        goals = list(model.goals)
        active = self._active_goal_index(goals)

        if active != self._active_index:
            self._following = True
        self._active_index = active
        self._goals = goals

        if self._following and active is not None:
            self._selected_goal = active
            self._selected_task = self._pinned_task_index(goals[active])

        self._analysis = model.analysis
        self._clamp()
        self._render_dashboard()

    def _clamp(self) -> None:
        if not self._goals:
            self._selected_goal = 0
            self._selected_task = 0
            return
        self._selected_goal = max(0, min(self._selected_goal, len(self._goals) - 1))
        tasks = self._goals[self._selected_goal].tasks
        self._selected_task = max(0, min(self._selected_task, max(0, len(tasks) - 1)))

    def action_goal_older(self) -> None:
        if self._selected_goal > 0:
            self._selected_goal -= 1
            self._selected_task = 0
            self._following = False
            self._clamp()
            self._render_dashboard()

    def action_goal_newer(self) -> None:
        if self._selected_goal < len(self._goals) - 1:
            self._selected_goal += 1
            self._selected_task = 0
            self._following = False
            self._clamp()
            self._render_dashboard()

    def action_task_prev(self) -> None:
        if self._selected_task > 0:
            self._selected_task -= 1
            self._following = False
            self._render_dashboard()

    def action_task_next(self) -> None:
        goal = self._selected_goal_obj()
        if goal and self._selected_task < len(goal.tasks) - 1:
            self._selected_task += 1
            self._following = False
            self._render_dashboard()

    def _render_dashboard(self) -> None:
        self._sync_goals()
        self.query_one("#dashboard-task", Static).update(
            _render_task_detail(self._selected_goal_obj(), self._selected_task)
        )
        self._render_sections()

    def _sync_goals(self) -> None:
        container = self.query_one("#dashboard-goals", VerticalScroll)
        if not self._goals:
            if self._goal_widgets or not container.children:
                self._goal_widgets = []
                container.remove_children()
                self.call_next(container.mount, Static(Text("No goals yet", style="dim")))
            return
        if len(self._goal_widgets) != len(self._goals):
            self._goal_widgets = [Static(id=f"goal-{index}", classes="goal-box") for index in range(len(self._goals))]
            container.remove_children()
            self.call_next(container.mount, *reversed(self._goal_widgets))
            self.call_next(self._paint_goals)
        else:
            self._paint_goals()

    def _paint_goals(self) -> None:
        for index, goal in enumerate(self._goals):
            if index < len(self._goal_widgets):
                self._goal_widgets[index].update(
                    _goal_panel(goal, index == self._selected_goal, index == self._active_index)
                )
        if 0 <= self._selected_goal < len(self._goal_widgets):
            self._goal_widgets[self._selected_goal].scroll_visible(animate=False)

    def _render_sections(self) -> None:
        analysis = self._analysis
        self.query_one("#dashboard-decisions", Static).update(
            _render_bullets(analysis.decisions) if analysis else Text("—", style="dim")
        )
        self.query_one("#dashboard-open", Static).update(
            _render_bullets(analysis.open_items) if analysis else Text("—", style="dim")
        )
        self.query_one("#dashboard-warnings", Static).update(
            _render_bullets(analysis.warnings) if analysis else Text("—", style="dim")
        )
