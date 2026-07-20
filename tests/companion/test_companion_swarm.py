"""Tests for companion Swarm parsing and rendering."""

from __future__ import annotations

import asyncio
import json

from swarm_harness import _agent, _summary, _SwarmHarness, _to_text
from test_companion_daemon import _build_fake_connection
from textual.widgets import Static

from basecamp.companion.daemon import (
    DaemonSkillInvocation,
    DaemonSummaryError,
    DaemonSummaryOk,
    DaemonSummarySource,
    DaemonSummaryUnavailable,
)
from basecamp.companion.ui.swarm import SwarmBody


def test_daemon_parser_reads_task_and_activity() -> None:
    payload = {
        "session_active": True,
        "root_id": "root",
        "counts": {"pending": 0, "running": 1, "completed": 0, "failed": 0, "total": 1},
        "agents": [
            {
                "agent_handle": "brisk-lynx-a1b2c3",
                "agent_id_short": "abc123",
                "agent_type": "worker",
                "model": "gpt-5.5",
                "role": "worker",
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
                "agent_handle": "brisk-lynx-a1b2c3",
                "agent_type": "worker",
                "role": "worker",
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
                        "isError": "bad",
                        "toolCount": "bad",
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
    assert len(agent.recent_activity) == 2
    assert agent.recent_activity[0].kind == "tool"
    assert agent.recent_activity[0].tool_name is None
    assert agent.recent_activity[0].is_error is None
    assert agent.recent_activity[0].tool_count is None
    assert agent.recent_activity[1].kind == "message"


def test_swarm_renders_skills_section_counts_and_empty_placeholder() -> None:
    swarm = SwarmBody()
    skilled = _summary(
        [
            _agent(
                skills=[
                    DaemonSkillInvocation(
                        name="python-development",
                        count=2,
                        last_seq=12,
                        last_timestamp="2026-01-01T00:00:04Z",
                    ),
                    DaemonSkillInvocation(
                        name="sql",
                        count=1,
                        last_seq=10,
                        last_timestamp="2026-01-01T00:00:02Z",
                    ),
                ]
            )
        ]
    )
    empty = _summary([_agent(skills=[])])

    async def run() -> None:
        async with _SwarmHarness(swarm).run_test() as pilot:
            swarm.update_daemon(skilled)
            await pilot.pause(0.1)
            detail_text = _to_text(swarm.query_one("#swarm-detail-content", Static).content)
            assert "Skills" in detail_text
            assert "python-development" in detail_text
            assert "×2" in detail_text
            assert "sql" in detail_text
            assert "sql · ×1" not in detail_text

            swarm.update_daemon(empty)
            await pilot.pause(0.1)
            detail_text = _to_text(swarm.query_one("#swarm-detail-content", Static).content)
            assert "Skills" in detail_text
            assert "│ —" in detail_text

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
            unavailable_text = _to_text(swarm.query_one("#swarm-detail-content", Static).content)
            assert "Daemon unavailable" in unavailable_text
            assert "socket missing" in unavailable_text

            swarm.update_daemon(DaemonSummaryError(error="bad daemon payload"))
            await pilot.pause(0.1)
            error_text = _to_text(swarm.query_one("#swarm-detail-content", Static).content)
            assert "Daemon error" in error_text
            assert "bad daemon payload" in error_text

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
