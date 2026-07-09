"""Tests for companion Swarm agent-message rendering."""

from __future__ import annotations

import asyncio

from basecamp.companion.daemon import (
    DaemonAgentMessage,
    DaemonAgentMessagesError,
    DaemonAgentMessagesOk,
    DaemonCurrentTask,
    DaemonRecentActivity,
    DaemonTaskPlanItem,
    DaemonTaskProgress,
    DaemonTaskProjection,
)
from basecamp.companion.ui.swarm import SwarmBody
from swarm_harness import _agent, _summary, _SwarmHarness, _to_text
from textual.widgets import Static


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
            swarm.update_agent_messages(
                DaemonAgentMessagesOk(
                    root_id="root",
                    agent_handle="brisk-lynx-a1b2c3",
                    messages=[
                        DaemonAgentMessage(
                            kind="assistant_output",
                            seq=6,
                            timestamp="2026-01-01T00:00:03Z",
                            label="assistant",
                            text="Older message should be hidden",
                        ),
                        DaemonAgentMessage(
                            kind="assistant_output",
                            seq=7,
                            timestamp="2026-01-01T00:00:04Z",
                            label="assistant",
                            text="First full message\nwith detail",
                        ),
                        DaemonAgentMessage(
                            kind="assistant_output",
                            seq=9,
                            timestamp="2026-01-01T00:00:06Z",
                            label="assistant",
                            text="Second full message",
                        ),
                        DaemonAgentMessage(
                            kind="agent_result",
                            seq=None,
                            timestamp="2026-01-01T00:00:07Z",
                            label="result",
                            text="Final full result",
                        ),
                    ],
                )
            )
            await pilot.pause(0.1)

            agents_panel = swarm.query_one("#swarm-agents")
            agents_text = _to_text(agents_panel.children[0].render())
            detail_text = _to_text(swarm.query_one("#swarm-detail-content", Static).content)

            assert "▸ ⏳ brisk-lynx-a1b2c3 (worker) [abc123]" in agents_text
            assert "scout-done (scout)" in agents_text
            assert "worker-failed (worker)" in agents_text
            assert "Build the thing task title" not in agents_text
            assert "failed worker task title" not in agents_text
            assert "completed" in agents_text
            assert "failed" in agents_text
            assert "brisk-lynx-a1b2c3 (worker)" in detail_text
            assert "Model: gpt-5.5" in detail_text
            assert "[abc123]" in detail_text
            assert "Goal: Build the thing" in detail_text
            assert "Progress: 1/3" in detail_text
            assert "Task plan" in detail_text
            assert "Current task" in detail_text
            assert "Skills" in detail_text
            assert detail_text.index("Task plan") < detail_text.index("Recent activity")
            assert detail_text.index("Current task") < detail_text.index("Recent activity")
            assert detail_text.index("Skills") < detail_text.index("Recent activity")
            assert "Now" in detail_text
            assert "Do current work" in detail_text
            assert "Important note" in detail_text
            assert "✎ note" in detail_text
            assert detail_text.index("✎ note") < detail_text.index("Recent activity")
            assert "Latest message" not in detail_text
            assert "Agent Messages" in detail_text
            assert detail_text.index("Recent activity") < detail_text.index("Agent Messages")
            assert "#8" in detail_text
            assert detail_text.index("#8") < detail_text.index("00:00:05")
            assert "Read file" in detail_text
            assert "opening /tmp/example.py" in detail_text
            assert "#9" in detail_text
            assert "assistant" in detail_text
            assert "Done with the thing" in detail_text
            assert "Older message should be hidden" not in detail_text
            assert "First full message" in detail_text
            assert "with detail" in detail_text
            assert "Second full message" in detail_text
            assert "Final full result" in detail_text
            assert detail_text.count("---") == 2
            assert "2026-01-01T00:00:05Z" not in detail_text

    asyncio.run(run())


def test_swarm_agent_messages_empty_error_and_stale_detail() -> None:
    swarm = SwarmBody()
    summary = _summary([_agent()])

    async def run() -> None:
        async with _SwarmHarness(swarm).run_test() as pilot:
            swarm.update_daemon(summary)
            await pilot.pause(0.1)
            detail_text = _to_text(swarm.query_one("#swarm-detail-content", Static).content)
            assert "Agent Messages" in detail_text

            swarm.update_agent_messages(DaemonAgentMessagesError(error="bad payload"))
            await pilot.pause(0.1)
            detail_text = _to_text(swarm.query_one("#swarm-detail-content", Static).content)
            assert "Messages error" in detail_text
            assert "bad payload" in detail_text

            swarm.update_agent_messages(
                DaemonAgentMessagesOk(
                    root_id="root",
                    agent_handle="other-agent",
                    messages=[
                        DaemonAgentMessage(
                            kind="assistant_output",
                            seq=1,
                            timestamp=None,
                            label="assistant",
                            text="stale message",
                        )
                    ],
                )
            )
            await pilot.pause(0.1)
            detail_text = _to_text(swarm.query_one("#swarm-detail-content", Static).content)
            assert "stale message" not in detail_text

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
