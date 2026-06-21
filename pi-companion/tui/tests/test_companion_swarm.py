"""Tests for companion Swarm parsing and rendering."""

from __future__ import annotations

import asyncio
import json
import re

from companion_tui.app import SwarmBody
from companion_tui.daemon import (
    DaemonCurrentTask,
    DaemonRecentActivity,
    DaemonSummaryAgent,
    DaemonSummaryCounts,
    DaemonSummaryOk,
    DaemonSummarySource,
    DaemonSummaryUnavailable,
    DaemonTaskPlanItem,
    DaemonTaskProgress,
    DaemonTaskProjection,
)
from rich.console import Console
from test_companion_daemon import _build_fake_connection
from textual.app import App, ComposeResult
from textual.widgets import Static


def _to_text(renderable: object) -> str:
    console = Console(width=100, no_color=True)
    with console.capture() as capture:
        console.print(renderable)
    return re.sub(r"\x1b\[[0-9;]*m", "", capture.get())


def _agent(**overrides: object) -> DaemonSummaryAgent:
    values = {
        "agent_handle": "worker-brisk-lynx",
        "agent_type": "worker",
        "role": "agent",
        "session_name": "worker",
        "status": "running",
        "result_preview": None,
        "error_preview": None,
        "exit_code": None,
        "created_at": "2026-01-01T00:00:00Z",
        "started_at": "2026-01-01T00:00:01Z",
        "ended_at": None,
    }
    values.update(overrides)
    return DaemonSummaryAgent(**values)


def _summary(agents: list[DaemonSummaryAgent]) -> DaemonSummaryOk:
    return DaemonSummaryOk(
        root_id="root",
        counts=DaemonSummaryCounts(
            pending=0,
            running=sum(1 for agent in agents if agent.status == "running"),
            completed=sum(1 for agent in agents if agent.status == "completed"),
            failed=sum(1 for agent in agents if agent.status == "failed"),
            total=len(agents),
        ),
        agents=agents,
        session_active=True,
    )


class _SwarmHarness(App[None]):
    def __init__(self, swarm: SwarmBody) -> None:
        super().__init__()
        self.swarm = swarm

    def compose(self) -> ComposeResult:
        yield self.swarm


def test_daemon_parser_reads_task_and_activity() -> None:
    payload = {
        "session_active": True,
        "root_id": "root",
        "counts": {"pending": 0, "running": 1, "completed": 0, "failed": 0, "total": 1},
        "agents": [
            {
                "agent_handle": "worker-brisk-lynx",
                "agent_id_short": "abc123",
                "agent_type": "worker",
                "model": "gpt-5.5",
                "role": "agent",
                "session_name": "worker",
                "status": "running",
                "result_preview": None,
                "error_preview": None,
                "exit_code": None,
                "created_at": "2026-01-01T00:00:00Z",
                "started_at": "2026-01-01T00:00:01Z",
                "ended_at": None,
                "task": {
                    "goal": "Build the thing",
                    "progress": {"completed": 1, "deleted": 0, "total": 3},
                    "task_plan": [
                        {"index": 0, "label": "Done", "status": "completed"},
                        {"index": 1, "label": "Now", "status": "active"},
                    ],
                    "current_task": {
                        "index": 1,
                        "label": "Now",
                        "status": "active",
                        "description": "Do current work",
                        "notes": "Important note",
                    },
                },
                "recent_activity": [
                    {
                        "kind": "tool",
                        "seq": 4,
                        "timestamp": "2026-01-01T00:00:02Z",
                        "category": "tool",
                        "label": "Read file",
                        "snippet": "daemon.py",
                        "toolName": "read",
                        "isError": False,
                        "turnIndex": 2,
                        "toolCount": 3,
                        "toolCallId": "call-123",
                        "raw": {"secret": "ignored"},
                        "message": "ignored",
                        "chainOfThought": "ignored",
                        "hidden": "ignored",
                    }
                ],
            }
        ],
    }
    fake_connection, _ = _build_fake_connection(json.dumps(payload))
    result = DaemonSummarySource("/tmp/daemon.sock", connection_factory=fake_connection).poll("root")

    assert isinstance(result, DaemonSummaryOk)
    agent = result.agents[0]
    assert agent.agent_id_short == "abc123"
    assert agent.model == "gpt-5.5"
    assert agent.task is not None
    assert agent.task.goal == "Build the thing"
    assert agent.task.progress is not None
    assert agent.task.progress.completed == 1
    assert [item.label for item in agent.task.task_plan] == ["Done", "Now"]
    assert agent.task.current_task is not None
    assert agent.task.current_task.notes == "Important note"
    assert agent.recent_activity is not None
    activity = agent.recent_activity[0]
    assert activity.tool_name == "read"
    assert activity.turn_index == 2
    assert activity.category == "tool"
    assert activity.label == "Read file"
    assert activity.snippet == "daemon.py"
    assert activity.is_error is False
    assert activity.tool_count == 3
    assert not hasattr(activity, "toolName")
    assert not hasattr(activity, "isError")
    assert not hasattr(activity, "turnIndex")
    assert not hasattr(activity, "toolCount")
    assert not hasattr(activity, "toolCallId")
    assert not hasattr(activity, "raw")
    assert not hasattr(activity, "message")
    assert not hasattr(activity, "chainOfThought")
    assert not hasattr(activity, "hidden")


def test_daemon_parser_tolerates_malformed_optional_projection() -> None:
    payload = {
        "session_active": True,
        "root_id": "root",
        "counts": {"pending": 0, "running": 1, "completed": 0, "failed": 0, "total": 1},
        "agents": [
            {
                "agent_handle": "worker-brisk-lynx",
                "agent_type": "worker",
                "role": "agent",
                "session_name": "worker",
                "status": "running",
                "result_preview": None,
                "error_preview": None,
                "exit_code": None,
                "created_at": "2026-01-01T00:00:00Z",
                "started_at": None,
                "ended_at": None,
                "task": {"goal": 123, "progress": {"completed": "bad"}, "tasks": ["bad"]},
                "recent_activity": [
                    {
                        "kind": "tool",
                        "seq": 4,
                        "timestamp": "2026-01-01T00:00:02Z",
                        "toolName": 123,
                    },
                    {
                        "kind": "message",
                        "seq": 5,
                        "timestamp": "2026-01-01T00:00:03Z",
                    },
                ],
            }
        ],
    }
    fake_connection, _ = _build_fake_connection(json.dumps(payload))
    result = DaemonSummarySource("/tmp/daemon.sock", connection_factory=fake_connection).poll("root")

    assert isinstance(result, DaemonSummaryOk)
    agent = result.agents[0]
    assert agent.agent_id_short is None
    assert agent.model is None
    assert agent.task is not None
    assert agent.task.goal is None
    assert agent.task.progress is None
    assert agent.task.task_plan == []
    assert agent.task.current_task is None
    assert agent.recent_activity is not None
    assert len(agent.recent_activity) == 1
    assert agent.recent_activity[0].kind == "message"
    assert agent.recent_activity[0].tool_name is None
    assert agent.recent_activity[0].tool_count is None


def test_swarm_renders_left_list_and_ordered_detail_sections() -> None:
    swarm = SwarmBody()
    summary = _summary(
        [
            _agent(
                session_name="Build the thing task title",
                agent_id_short="abc123",
                model="gpt-5.5",
                task=result_task(),
                recent_activity=[
                    DaemonRecentActivity(
                        kind="tool_call",
                        seq=8,
                        timestamp="2026-01-01T00:00:05Z",
                        tool_name="read",
                        turn_index=3,
                        category="tool",
                        label="Read file",
                        snippet="opening /tmp/example.py",
                        is_error=False,
                        tool_count=1,
                    ),
                    DaemonRecentActivity(
                        kind="assistant_output",
                        seq=9,
                        timestamp="2026-01-01T00:00:06Z",
                        tool_name=None,
                        turn_index=3,
                        label=None,
                        snippet="Done with the thing",
                    ),
                ],
            ),
            _agent(
                agent_handle="scout-done",
                agent_type="scout",
                session_name="scout task title",
                status="completed",
                ended_at="2026-01-01T00:00:04Z",
            ),
            _agent(
                agent_handle="worker-failed",
                session_name="failed worker task title",
                status="failed",
                ended_at="2026-01-01T00:00:04Z",
            ),
        ]
    )

    async def run() -> None:
        async with _SwarmHarness(swarm).run_test() as pilot:
            swarm.update_daemon(summary)
            await pilot.pause(0.1)

            agents_panel = swarm.query_one("#swarm-agents")
            agents_text = _to_text(agents_panel.children[0].render())
            detail_text = _to_text(swarm.query_one("#swarm-detail-content", Static).content)

            assert "▸ ⏳ worker-brisk-lynx (worker) [abc123]" in agents_text
            assert "scout-done (scout)" in agents_text
            assert "worker-failed (worker)" in agents_text
            assert "Build the thing task title" not in agents_text
            assert "failed worker task title" not in agents_text
            assert "completed" in agents_text
            assert "failed" in agents_text
            assert "worker-brisk-lynx (worker)" in detail_text
            assert "Model: gpt-5.5" in detail_text
            assert "[abc123]" in detail_text
            assert "Goal: Build the thing" in detail_text
            assert "Progress: 1/3" in detail_text
            assert detail_text.index("Task plan") < detail_text.index("Current task")
            assert "Now" in detail_text
            assert "Do current work" in detail_text
            assert "Important note" in detail_text
            assert "✎ note" in detail_text
            assert (
                detail_text.index("Current task") < detail_text.index("✎ note") < detail_text.index("Recent activity")
            )
            assert "Latest message" not in detail_text
            assert "Recent activity" in detail_text
            assert "#8" in detail_text
            assert detail_text.index("#8") < detail_text.index("00:00:05")
            assert "Read file" in detail_text
            assert "opening /tmp/example.py" in detail_text
            assert "#9" in detail_text
            assert "assistant" in detail_text
            assert "Done with the thing" in detail_text
            assert "2026-01-01T00:00:05Z" not in detail_text

    asyncio.run(run())


def test_swarm_repeated_updates_keep_one_agent_list_child() -> None:
    swarm = SwarmBody()
    summary = _summary([_agent(agent_handle="first-agent", session_name="first", status="running")])

    async def run() -> None:
        async with _SwarmHarness(swarm).run_test() as pilot:
            swarm.update_daemon(summary)
            swarm.update_daemon(summary)
            swarm.update_daemon(summary)
            await pilot.pause(0.1)

            agents_panel = swarm.query_one("#swarm-agents")
            assert len(agents_panel.children) == 1
            assert "first-agent" in _to_text(agents_panel.children[0].render())

    asyncio.run(run())


def test_swarm_empty_unavailable_and_selection_clamping() -> None:
    swarm = SwarmBody()
    first = _agent(session_name="first", status="running")
    second = _agent(session_name="second", status="running")

    async def run() -> None:
        async with _SwarmHarness(swarm).run_test() as pilot:
            swarm.update_daemon(None)
            await pilot.pause(0.1)
            assert "No session snapshot yet" in _to_text(swarm.query_one("#swarm-detail-content", Static).content)

            swarm.update_daemon(DaemonSummaryUnavailable(error="socket missing"))
            await pilot.pause(0.1)
            assert "Daemon unavailable" in _to_text(swarm.query_one("#swarm-detail-content", Static).content)

            swarm.update_daemon(_summary([first, second]))
            await pilot.pause(0.1)
            detail_text = _to_text(swarm.query_one("#swarm-detail-content", Static).content)
            assert swarm._selected_agent == 0
            assert "Model: —" in detail_text
            assert "Goal: —" in detail_text
            assert "Progress: —" in detail_text

            swarm.action_select_next()
            assert swarm._selected_agent == 1
            swarm.action_select_next()
            assert swarm._selected_agent == 1
            swarm.action_select_prev()
            assert swarm._selected_agent == 0
            swarm.action_select_prev()
            assert swarm._selected_agent == 0

            swarm._selected_agent = 8
            swarm.update_daemon(_summary([first]))
            assert swarm._selected_agent == 0

    asyncio.run(run())


def result_task() -> DaemonTaskProjection:
    return DaemonTaskProjection(
        goal="Build the thing",
        progress=DaemonTaskProgress(completed=1, deleted=0, total=3),
        task_plan=[
            DaemonTaskPlanItem(index=0, label="Done", status="completed"),
            DaemonTaskPlanItem(index=1, label="Now", status="active"),
            DaemonTaskPlanItem(index=2, label="Later", status="pending"),
        ],
        current_task=DaemonCurrentTask(
            index=1,
            label="Now",
            status="active",
            description="Do current work",
            notes="Important note",
        ),
    )
