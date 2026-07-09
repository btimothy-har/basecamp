"""Swarm body and rendering helpers for the companion TUI."""

from __future__ import annotations

from datetime import datetime

from basecamp.companion.daemon import (
    DaemonAgentMessage,
    DaemonAgentMessages,
    DaemonRecentActivity,
    DaemonSummary,
    DaemonSummaryAgent,
)
from basecamp.companion.ui.formatting import (
    _STATUS_GLYPH,
    _format_activity_timestamp,
    _format_duration,
    _parse_iso_timestamp,
    _truncate_preview,
)
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

_DAEMON_STATUS_GLYPH = {
    "completed": "✓",
    "active": "▶",
    "running": "⏳",
    "pending": "○",
    "failed": "✕",
    "error": "✕",
}


def _daemon_agent_timing(agent: DaemonSummaryAgent) -> str | None:
    start = _parse_iso_timestamp(agent.started_at or agent.created_at)
    end = _parse_iso_timestamp(agent.ended_at)

    if start is None:
        return None

    now = datetime.now(start.tzinfo)

    if end is not None:
        label = "elapsed"
        end_time = end
    else:
        label = "running"
        end_time = now

    if end_time is None:
        return None

    try:
        duration = end_time - start
    except (TypeError, OverflowError):
        return None

    total_seconds = max(0, int(duration.total_seconds()))
    return f"{label} {_format_duration(total_seconds)}"


def _render_swarm_unavailable(summary: DaemonSummary | None) -> Text:
    if summary is None:
        return Text("No session snapshot yet", style="dim")

    if summary.state == "unavailable":
        text = Text("Daemon unavailable")
        if summary.error:
            text.append(" · ")
            text.append(_truncate_preview(summary.error, max_length=120), style="dim")
        return text

    if summary.state == "error":
        text = Text("Daemon error")
        if summary.error:
            text.append(" · ")
            text.append(_truncate_preview(summary.error, max_length=120), style="dim")
        return text

    return Text("No async agents yet", style="dim")


def _render_swarm_agents(summary: DaemonSummary | None, selected_index: int) -> Text:
    if summary is None or summary.state != "ok" or not summary.agents:
        return _render_swarm_unavailable(summary)

    rows = Text()
    for index, agent in enumerate(summary.agents):
        if index:
            rows.append("\n")

        status = agent.status.lower()
        glyph = _DAEMON_STATUS_GLYPH.get(status, "•")
        marker = "▸" if index == selected_index else " "
        row_style = "reverse" if index == selected_index else ""
        timing = _daemon_agent_timing(agent)

        row = Text(style=row_style)
        row.append(f"{marker} {glyph} ")
        row.append(agent.agent_handle, style=f"bold {row_style}".strip())
        if agent.agent_type:
            row.append(f" ({agent.agent_type})")
        if agent.agent_id_short:
            row.append(f" [{agent.agent_id_short}]", style=f"dim {row_style}".strip())

        details = " · ".join(part for part in (agent.status, timing) if part)
        if details:
            row.append(f"\n    {details}", style=f"dim {row_style}".strip())
        rows.append_text(row)
    return rows


def _swarm_section(title: str, body: RenderableType) -> Panel:
    return Panel(body, title=Text(title, style="bold"), title_align="left", border_style="grey42", padding=(0, 1))


def _render_swarm_header(agent: DaemonSummaryAgent) -> Text:
    text = Text()
    text.append(agent.agent_handle, style="bold")
    if agent.agent_type:
        text.append(f" ({agent.agent_type})", style="dim")

    metadata = [agent.status]
    timing = _daemon_agent_timing(agent)
    if timing:
        metadata.append(timing)
    if agent.agent_id_short:
        metadata.append(f"[{agent.agent_id_short}]")
    metadata.append(f"Model: {agent.model or '—'}")
    text.append("\n")
    text.append(" · ".join(metadata), style="dim")

    goal = agent.task.goal if agent.task and agent.task.goal else None
    text.append("\nGoal: ", style="bold")
    text.append(goal or "—", style="" if goal else "dim")

    text.append("\nProgress: ", style="bold")
    if agent.task and agent.task.progress:
        progress = agent.task.progress
        text.append(f"{progress.completed}/{progress.total}")
        if progress.deleted:
            text.append(f" · {progress.deleted} deleted", style="dim")
    else:
        text.append("—", style="dim")
    return text


def _render_swarm_task_plan(agent: DaemonSummaryAgent) -> Text:
    if not agent.task or not agent.task.task_plan:
        return Text("—", style="dim")

    rows = Text()
    for index, item in enumerate(agent.task.task_plan):
        if index:
            rows.append("\n")
        glyph = _STATUS_GLYPH.get(item.status, _DAEMON_STATUS_GLYPH.get(item.status.lower(), "•"))
        rows.append(f"{glyph} [{item.index + 1}] ")
        rows.append(item.label, style="bold" if item.status == "active" else "")
        rows.append(f" · {item.status}", style="dim")
    return rows


def _render_swarm_current_task(agent: DaemonSummaryAgent) -> RenderableType:
    task = agent.task.current_task if agent.task else None
    if task is None:
        return Text("—", style="dim")

    header = Text()
    glyph = _STATUS_GLYPH.get(task.status, _DAEMON_STATUS_GLYPH.get(task.status.lower(), "•"))
    header.append(f"[{task.index + 1}] {glyph} ")
    header.append(task.label, style="bold")
    header.append(f" · {task.status}", style="dim")
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


def _activity_label(activity: DaemonRecentActivity) -> str:
    if activity.label:
        return activity.label
    if activity.tool_name:
        return activity.tool_name

    labels = {
        "assistant_output": "assistant",
        "agent_result": "result",
        "thinking": "thinking",
        "tool_call": "tool",
        "tool": "tool",
        "message": "message",
    }
    return labels.get(activity.kind, activity.kind)


def _activity_snippet(activity: DaemonRecentActivity) -> str | None:
    if activity.snippet:
        return activity.snippet
    if activity.tool_name:
        return activity.tool_name
    if activity.turn_index is not None:
        return f"turn {activity.turn_index}"
    if activity.tool_count is not None:
        return f"{activity.tool_count} tools"
    return None


def _render_swarm_skills(agent: DaemonSummaryAgent) -> Text:
    if not agent.skills:
        return Text("—", style="dim")

    rows = Text()
    for index, skill in enumerate(agent.skills):
        if index:
            rows.append("\n")
        rows.append(skill.name, style="bold")
        if skill.count > 1:
            rows.append(f" · ×{skill.count}", style="dim")
    return rows


def _render_swarm_recent_activity(agent: DaemonSummaryAgent) -> Text:
    if not agent.recent_activity:
        return Text("—", style="dim")

    rows = Text()
    for index, activity in enumerate(agent.recent_activity[:16]):
        if index:
            rows.append("\n")

        seq = f"#{activity.seq}" if activity.seq is not None else "#—"
        timestamp = _format_activity_timestamp(activity.timestamp) or "—"
        label = _truncate_preview(_activity_label(activity), max_length=32)
        snippet = _activity_snippet(activity)
        snippet = _truncate_preview(snippet, max_length=120) if snippet else "—"

        row = Text()
        row.append(f"{seq}  ", style="dim")
        row.append(f"{timestamp}  ", style="dim")
        if activity.is_error is True:
            row.append("error ", style="red bold")
        row.append(f"{label}  ", style="bold" if activity.is_error is not True else "red bold")
        row.append(snippet, style="red" if activity.is_error is True else "")
        rows.append_text(row)
    return rows


def _agent_message_label(message: DaemonAgentMessage) -> str:
    if message.label:
        return message.label
    if message.kind == "agent_result":
        return "result"
    return "assistant"


def _render_swarm_agent_messages(
    agent: DaemonSummaryAgent,
    messages: DaemonAgentMessages | None,
) -> Text:
    if messages is None:
        return Text("—", style="dim")
    if messages.state == "unavailable":
        text = Text("Messages unavailable")
        if messages.error:
            text.append(" · ")
            text.append(_truncate_preview(messages.error, max_length=80), style="dim")
        return text
    if messages.state == "error":
        text = Text("Messages error")
        if messages.error:
            text.append(" · ")
            text.append(_truncate_preview(messages.error, max_length=80), style="dim")
        return text
    if messages.agent_handle != agent.agent_handle or not messages.messages:
        return Text("—", style="dim")

    rows = Text()
    for index, message in enumerate(messages.messages[-3:]):
        if index:
            rows.append("\n---\n", style="dim")
        label = _truncate_preview(_agent_message_label(message), max_length=32)
        timestamp = _format_activity_timestamp(message.timestamp)
        rows.append(label, style="bold")
        if timestamp:
            rows.append(f" · {timestamp}", style="dim")
        rows.append("\n")
        rows.append(message.text)
    return rows


def _render_swarm_detail(
    summary: DaemonSummary | None,
    selected_index: int,
    messages: DaemonAgentMessages | None = None,
) -> RenderableType:
    if summary is None or summary.state != "ok" or not summary.agents:
        return _render_swarm_unavailable(summary)

    index = max(0, min(selected_index, len(summary.agents) - 1))
    agent = summary.agents[index]
    header = _render_swarm_header(agent)
    left_group = Group(
        _swarm_section("Task plan", _render_swarm_task_plan(agent)),
        _swarm_section("Current task", _render_swarm_current_task(agent)),
    )
    right_cell = _swarm_section("Skills", _render_swarm_skills(agent))
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    grid.add_row(left_group, right_cell)
    recent_activity_section = _swarm_section("Recent activity", _render_swarm_recent_activity(agent))
    agent_messages_section = _swarm_section("Agent Messages", _render_swarm_agent_messages(agent, messages))
    return Group(header, grid, recent_activity_section, agent_messages_section)


class SwarmBody(Widget):
    """Swarm modality body showing daemon-backed async agent observability."""

    can_focus = True

    BINDINGS = [
        Binding("m", "app.toggle_mode", "Mode"),
        Binding("up", "select_prev", "Prev agent"),
        Binding("down", "select_next", "Next agent"),
    ]

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._summary: DaemonSummary | None = None
        self._messages: DaemonAgentMessages | None = None
        self._selected_agent = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="swarm-layout"):
            with VerticalScroll(id="swarm-agents", classes="swarm-box"):
                yield Static(id="swarm-agents-content")
            with VerticalScroll(id="swarm-detail", classes="swarm-box"):
                yield Static(id="swarm-detail-content")

    def render(self) -> Text:
        return Text()

    def on_mount(self) -> None:
        self.query_one("#swarm-agents", VerticalScroll).border_title = "Agents"
        self.query_one("#swarm-detail", VerticalScroll).border_title = "Agent detail"
        self.update_daemon(None)

    def update_daemon(self, summary: DaemonSummary | None) -> None:
        previous_handle = self.selected_agent_handle()
        self._summary = summary
        self._clamp_selection()
        if self.selected_agent_handle() != previous_handle:
            self._messages = None
        self._render_swarm()

    def update_agent_messages(self, messages: DaemonAgentMessages | None) -> None:
        self._messages = messages
        self._render_swarm()

    def selected_agent_handle(self) -> str | None:
        if self._summary is None or self._summary.state != "ok" or not self._summary.agents:
            return None
        index = max(0, min(self._selected_agent, len(self._summary.agents) - 1))
        return self._summary.agents[index].agent_handle

    def action_select_prev(self) -> None:
        if self._agent_count() < 2:
            return
        previous_handle = self.selected_agent_handle()
        self._selected_agent = max(0, self._selected_agent - 1)
        if self.selected_agent_handle() != previous_handle:
            self._messages = None
        self._render_swarm()

    def action_select_next(self) -> None:
        if self._agent_count() < 2:
            return
        previous_handle = self.selected_agent_handle()
        self._selected_agent = min(self._agent_count() - 1, self._selected_agent + 1)
        if self.selected_agent_handle() != previous_handle:
            self._messages = None
        self._render_swarm()

    def _agent_count(self) -> int:
        if self._summary is None or self._summary.state != "ok":
            return 0
        return len(self._summary.agents)

    def _clamp_selection(self) -> None:
        count = self._agent_count()
        if count == 0:
            self._selected_agent = 0
            return
        self._selected_agent = max(0, min(self._selected_agent, count - 1))

    def _render_swarm(self) -> None:
        self.query_one("#swarm-agents-content", Static).update(
            _render_swarm_agents(self._summary, self._selected_agent)
        )
        self.query_one("#swarm-detail-content", Static).update(
            _render_swarm_detail(self._summary, self._selected_agent, self._messages)
        )
