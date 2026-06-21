"""Tests for companion Swarm parsing and rendering."""

from __future__ import annotations

import asyncio
import json

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
    return capture.get()


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
                        "toolName": "read",
                        "turnIndex": 2,
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
    assert agent.task is not None
    assert agent.task.goal == "Build the thing"
    assert agent.task.progress is not None
    assert agent.task.progress.completed == 1
    assert [item.label for item in agent.task.task_plan] == ["Done", "Now"]
    assert agent.task.current_task is not None
    assert agent.task.current_task.notes == "Important note"
    assert agent.recent_activity is not None
    assert agent.recent_activity[0].tool_name == "read"
    assert agent.recent_activity[0].turn_index == 2
    assert not hasattr(agent.recent_activity[0], "toolName")
    assert not hasattr(agent.recent_activity[0], "turnIndex")
    assert not hasattr(agent.recent_activity[0], "hidden")


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
                "recent_activity": {"bad": "shape"},
            }
        ],
    }
    fake_connection, _ = _build_fake_connection(json.dumps(payload))
    result = DaemonSummarySource("/tmp/daemon.sock", connection_factory=fake_connection).poll("root")

    assert isinstance(result, DaemonSummaryOk)
    agent = result.agents[0]
    assert agent.task is not None
    assert agent.task.goal is None
    assert agent.task.progress is None
    assert agent.task.task_plan == []
    assert agent.task.current_task is None
    assert agent.recent_activity == []


def test_swarm_renders_left_list_and_ordered_detail_sections() -> None:
    swarm = SwarmBody()
    long_tool = "tool-" + "y" * 220
    summary = _summary(
        [
            _agent(
                task=result_task(),
                recent_activity=[
                    DaemonRecentActivity(
                        kind="tool",
                        seq=8,
                        timestamp="2026-01-01T00:00:05Z",
                        tool_name=long_tool,
                        turn_index=3,
                    )
                ],
            ),
            _agent(
                agent_handle="scout-done",
                agent_type="scout",
                session_name="scout",
                status="completed",
                ended_at="2026-01-01T00:00:04Z",
            ),
            _agent(
                agent_handle="worker-failed",
                session_name="failed worker",
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

            assert "worker" in agents_text
            assert "scout" in agents_text
            assert "failed worker" in agents_text
            assert "completed" in agents_text
            assert "failed" in agents_text
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
            assert "tool" in detail_text
            assert "turn 3" in detail_text
            assert "2026-01-01T00:00:05Z" in detail_text

    asyncio.run(run())


def test_swarm_repeated_updates_keep_one_agent_list_child() -> None:
    swarm = SwarmBody()
    summary = _summary([_agent(session_name="first", status="running")])

    async def run() -> None:
        async with _SwarmHarness(swarm).run_test() as pilot:
            swarm.update_daemon(summary)
            swarm.update_daemon(summary)
            swarm.update_daemon(summary)
            await pilot.pause(0.1)

            agents_panel = swarm.query_one("#swarm-agents")
            assert len(agents_panel.children) == 1
            assert "first" in _to_text(agents_panel.children[0].render())

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
            assert swarm._selected_agent == 0

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
