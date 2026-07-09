"""Shared harness and builders for companion Swarm rendering tests."""

from __future__ import annotations

import re

from basecamp.companion.daemon import DaemonSummaryAgent, DaemonSummaryCounts, DaemonSummaryOk
from basecamp.companion.ui.swarm import SwarmBody
from rich.console import Console
from textual.app import App, ComposeResult


def _to_text(renderable: object) -> str:
    console = Console(width=100, no_color=True)
    with console.capture() as capture:
        console.print(renderable)
    return re.sub(r"\x1b\[[0-9;]*m", "", capture.get())


def _agent(**overrides: object) -> DaemonSummaryAgent:
    values = {
        "agent_handle": "brisk-lynx-a1b2c3",
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
