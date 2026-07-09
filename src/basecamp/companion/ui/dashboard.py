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

from basecamp.companion.analysis import CompanionAnalysis
from basecamp.companion.snapshot import CompanionGoal
from basecamp.companion.source import DashboardModel
from basecamp.companion.ui.formatting import _STATUS_GLYPH

VISIBLE_OTHER_GOAL_LIMIT = 5


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


def _collapsed_goals_row(count: int) -> Text:
    """Render the compact hidden-goals placeholder row."""

    label = "goal" if count == 1 else "goals"
    return Text(f"+ {count} hidden {label}", style="dim")


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
        self._goal_widgets: dict[int, Static] = {}
        self._rendered_goal_indices: list[int] = []
        self._collapsed_goal_count = 0

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="dashboard-goals")
        with Vertical(id="dashboard-main"):
            yield Static(id="dashboard-task", classes="dashboard-box")
            yield Static(id="dashboard-monitor", classes="dashboard-box")
            with Horizontal(id="dashboard-bottom"):
                yield Static(id="dashboard-capture", classes="dashboard-box")
                yield Static(id="dashboard-checkpoints", classes="dashboard-box")

    def render(self) -> Text:
        return Text()

    def on_mount(self) -> None:
        goals_panel = self.query_one("#dashboard-goals", VerticalScroll)
        goals_panel.border_title = "Goals"
        goals_panel.can_focus = False
        self.query_one("#dashboard-task", Static).border_title = "Task"
        self.query_one("#dashboard-monitor", Static).border_title = "Monitor"
        self.query_one("#dashboard-capture", Static).border_title = "Needs capture"
        self.query_one("#dashboard-checkpoints", Static).border_title = "Checkpoints"
        self._render_dashboard()

    @staticmethod
    def _active_goal_index(goals: list[CompanionGoal]) -> int | None:
        for index, goal in enumerate(goals):
            if goal.active:
                return index
        return len(goals) - 1 if goals else None

    @staticmethod
    def _visible_goal_indices(
        goals: list[CompanionGoal], active_index: int | None, selected_goal: int
    ) -> tuple[list[int], int]:
        """Return chronological visible goal indices plus hidden count."""

        if not goals:
            return [], 0

        recent_others = [
            index for index in range(len(goals) - 1, -1, -1) if active_index is None or index != active_index
        ][:VISIBLE_OTHER_GOAL_LIMIT]
        visible = set(recent_others)
        if active_index is not None:
            visible.add(active_index)
        if 0 <= selected_goal < len(goals):
            visible.add(selected_goal)
        visible_indices = sorted(visible)
        return visible_indices, len(goals) - len(visible_indices)

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
                self._goal_widgets = {}
                self._rendered_goal_indices = []
                self._collapsed_goal_count = 0
                container.remove_children()
                self.call_next(container.mount, Static(Text("No goals yet", style="dim")))
            return

        visible_indices, collapsed_count = self._visible_goal_indices(
            self._goals, self._active_index, self._selected_goal
        )
        if visible_indices != self._rendered_goal_indices or collapsed_count != self._collapsed_goal_count:
            self._goal_widgets = {index: Static(id=f"goal-{index}", classes="goal-box") for index in visible_indices}
            self._rendered_goal_indices = visible_indices
            self._collapsed_goal_count = collapsed_count
            children: list[Static] = [self._goal_widgets[index] for index in reversed(visible_indices)]
            if collapsed_count:
                children.append(Static(_collapsed_goals_row(collapsed_count), id="goal-history-collapsed"))
            container.remove_children()
            self.call_next(container.mount, *children)
            self.call_next(self._paint_goals)
        else:
            self._paint_goals()

    def _paint_goals(self) -> None:
        for index, widget in self._goal_widgets.items():
            widget.update(_goal_panel(self._goals[index], index == self._selected_goal, index == self._active_index))
        if self._selected_goal in self._goal_widgets:
            self._goal_widgets[self._selected_goal].scroll_visible(animate=False)

    def _render_sections(self) -> None:
        analysis = self._analysis
        self.query_one("#dashboard-monitor", Static).update(
            _render_bullets(analysis.monitor) if analysis else Text("—", style="dim")
        )
        self.query_one("#dashboard-capture", Static).update(
            _render_bullets(analysis.needs_capture) if analysis else Text("—", style="dim")
        )
        self.query_one("#dashboard-checkpoints", Static).update(
            _render_bullets(analysis.checkpoints) if analysis else Text("—", style="dim")
        )
