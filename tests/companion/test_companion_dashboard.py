"""Tests for the companion dashboard sources and daemon polling."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from rich.console import Console
from textual.containers import VerticalScroll
from textual.widgets import ContentSwitcher, Static

from basecamp.companion.analysis import CompanionAnalysis
from basecamp.companion.app import CompanionApp
from basecamp.companion.daemon import (
    DaemonAgentMessages,
    DaemonAgentMessagesOk,
    DaemonSummary,
    DaemonSummaryAgent,
    DaemonSummaryCounts,
    DaemonSummaryError,
    DaemonSummaryOk,
    DaemonSummaryUnavailable,
)
from basecamp.companion.snapshot import CompanionGoal, CompanionProgress, CompanionTask
from basecamp.companion.source import DashboardModel
from basecamp.companion.ui.dashboard import DashboardBody
from basecamp.companion.ui.swarm import SwarmBody


def _to_text(renderable: object) -> str:
    console = Console(width=60, no_color=True)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)  # noqa: S603


def _build_repo(repo: Path) -> None:
    repo.mkdir()
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.email", "smoke@example.com")
    _run_git(repo, "config", "user.name", "Smoke Test")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "base commit")


class _FakeDaemonSource:
    def __init__(
        self,
        summary: DaemonSummary | None,
        messages: DaemonAgentMessages | None = None,
        analysis: CompanionAnalysis | None = None,
    ) -> None:
        self.summary = summary
        self.messages = messages
        self.analysis = analysis
        self.poll_calls: list[str] = []
        self.message_poll_calls: list[tuple[str, str, int | None]] = []

    def poll(self, root_id: str, limit: int | None = None) -> DaemonSummary | None:
        self.poll_calls.append(root_id)
        assert limit is None or isinstance(limit, int)
        return self.summary

    def poll_analysis(self, session_id: str) -> CompanionAnalysis | None:  # noqa: ARG002
        return self.analysis

    def poll_messages(
        self,
        root_id: str,
        agent_handle: str,
        limit: int | None = None,
    ) -> DaemonAgentMessages:
        self.message_poll_calls.append((root_id, agent_handle, limit))
        assert limit is None or isinstance(limit, int)
        return self.messages or DaemonAgentMessagesOk(root_id=root_id, agent_handle=agent_handle, messages=[])


class _DaemonPollError(Exception):
    def __init__(self, root_id: str) -> None:
        super().__init__(f"daemon failed for {root_id}")


class _FailingDaemonSource:
    def poll(self, root_id: str) -> DaemonSummary:
        raise _DaemonPollError(root_id)


def _goal(name: str, tasks: list[CompanionTask], *, active: bool, completed: int, total: int) -> CompanionGoal:
    return CompanionGoal(
        goal=name,
        tasks=tasks,
        agent_mode=None,
        active=active,
        archived_at=None if active else "2025-01-01T00:00:00Z",
        progress=CompanionProgress(completed=completed, total=total),
    )


def _daemon_summary_ok(
    *,
    total: int,
    agents: list[DaemonSummaryAgent],
    session_active: bool = True,
) -> DaemonSummaryOk:
    return DaemonSummaryOk(
        root_id="root",
        counts=DaemonSummaryCounts(pending=0, running=0, completed=total, failed=0, total=total),
        agents=agents,
        session_active=session_active,
    )


def test_dashboard_source_cache_tracks_session_id(tmp_path: Path) -> None:
    app = CompanionApp(
        snapshot_path=tmp_path / "snapshot.json",
        cwd=tmp_path,
        tasks_dir=tmp_path / "tasks",
    )

    first = app._ensure_dashboard_source("session-one")
    assert app._ensure_dashboard_source("session-one") is first

    second = app._ensure_dashboard_source("session-two")
    assert second is not first
    assert app._dashboard_source_session_id == "session-two"


def test_poll_daemon_summary_converts_unexpected_source_errors(tmp_path: Path) -> None:
    app = CompanionApp(
        snapshot_path=tmp_path / "snapshot.json",
        cwd=tmp_path,
        daemon_source=_FailingDaemonSource(),
    )

    result = app._poll_daemon_summary("session-123")

    assert isinstance(result, DaemonSummaryError)
    assert "session-123" in result.error


def test_swarm_receives_daemon_summary_when_session_active(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    session_id = "dead-beef-cafe-babe"
    snapshot_path.write_text(
        json.dumps({"version": 1, "sessionId": session_id, "updatedAt": "t", "effectiveCwd": str(repo)}),
        encoding="utf-8",
    )
    (tasks_dir / f"{session_id}.json").write_text(
        json.dumps(
            [
                {
                    "goal": "Dashboard goal",
                    "tasks": [
                        {"label": "T1", "description": "d1", "criteria": "c1", "status": "active", "notes": None}
                    ],
                    "agentMode": None,
                    "active": True,
                    "archivedAt": None,
                }
            ]
        ),
        encoding="utf-8",
    )
    daemon_source = _FakeDaemonSource(
        _daemon_summary_ok(
            total=0,
            agents=[],
            session_active=True,
        )
    )
    app = CompanionApp(
        snapshot_path=snapshot_path,
        cwd=repo,
        tasks_dir=tasks_dir,
        daemon_source=daemon_source,
    )

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            dash = app.query_one("#dashboard-body", DashboardBody)
            for _ in range(100):
                if dash._active_index is not None and app.query("#goal-0"):
                    break
                await pilot.pause(0.02)
            else:
                raise AssertionError

            app.query_one("#swarm-body", SwarmBody)
            swarm_detail = app.query_one("#swarm-detail-content", Static)
            assert "No async agents yet" in _to_text(swarm_detail.content)
            assert not app.query("#dashboard-daemon")
            assert daemon_source.poll_calls[-1] == session_id

    asyncio.run(run())


def test_swarm_polls_messages_for_selected_agent_when_session_active(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    session_id = "feed-beef-cafe-babe"
    snapshot_path.write_text(
        json.dumps({"version": 1, "sessionId": session_id, "updatedAt": "t", "effectiveCwd": str(repo)}),
        encoding="utf-8",
    )
    (tasks_dir / f"{session_id}.json").write_text("[]", encoding="utf-8")
    daemon_source = _FakeDaemonSource(
        _daemon_summary_ok(
            total=2,
            agents=[
                DaemonSummaryAgent(
                    agent_handle="selected-agent",
                    agent_type="worker",
                    role="worker",
                    session_name="selected",
                    status="running",
                    result_preview=None,
                    error_preview=None,
                    exit_code=None,
                    created_at="2026-01-01T00:00:00Z",
                    started_at="2026-01-01T00:00:01Z",
                    ended_at=None,
                ),
                DaemonSummaryAgent(
                    agent_handle="other-agent",
                    agent_type="scout",
                    role="worker",
                    session_name="other",
                    status="running",
                    result_preview=None,
                    error_preview=None,
                    exit_code=None,
                    created_at="2026-01-01T00:00:00Z",
                    started_at="2026-01-01T00:00:01Z",
                    ended_at=None,
                ),
            ],
        )
    )
    app = CompanionApp(
        snapshot_path=snapshot_path,
        cwd=repo,
        tasks_dir=tasks_dir,
        daemon_source=daemon_source,
    )

    async def run() -> None:
        async with app.run_test() as pilot:
            for _ in range(100):
                if daemon_source.message_poll_calls:
                    break
                await pilot.pause(0.02)
            else:
                raise AssertionError

            assert daemon_source.message_poll_calls[-1] == (session_id, "selected-agent", None)
            assert all(call[1] != "other-agent" for call in daemon_source.message_poll_calls)

    asyncio.run(run())


def test_dashboard_autopin_navigation_and_repin(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    session_id = "abcd-1234-5678-90ef"
    snapshot_path.write_text(
        json.dumps({"version": 1, "sessionId": session_id, "updatedAt": "t", "effectiveCwd": str(repo)}),
        encoding="utf-8",
    )
    (tasks_dir / f"{session_id}.json").write_text(
        json.dumps(
            [
                {
                    "goal": "First goal",
                    "tasks": [
                        {"label": "T1", "description": "d1", "criteria": "c1", "status": "completed", "notes": "n1"},
                        {"label": "T2", "description": "d2", "criteria": "c2", "status": "completed", "notes": None},
                    ],
                    "agentMode": "work",
                    "active": False,
                    "archivedAt": "2025-01-01T00:00:00Z",
                },
                {
                    "goal": "Second goal",
                    "tasks": [
                        {"label": "T3", "description": "d3", "criteria": "c3", "status": "completed", "notes": None},
                        {"label": "T4", "description": "d4", "criteria": "c4", "status": "active", "notes": "wip"},
                    ],
                    "agentMode": None,
                    "active": True,
                    "archivedAt": None,
                },
            ]
        ),
        encoding="utf-8",
    )
    daemon_source = _FakeDaemonSource(
        DaemonSummaryUnavailable(error="unavailable in test"),
        analysis=CompanionAnalysis(monitor=["monitor1"], needs_capture=["capture1"], checkpoints=["checkpoint1"]),
    )
    app = CompanionApp(
        snapshot_path=snapshot_path,
        cwd=repo,
        tasks_dir=tasks_dir,
        daemon_source=daemon_source,
    )

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            dash = app.query_one("#dashboard-body", DashboardBody)
            # Wait for the dashboard to load goals + mount goal widgets (mount + first
            # refresh + call_after_refresh) instead of a fixed sleep.
            for _ in range(100):
                if dash._active_index is not None and app.query("#goal-1"):
                    break
                await pilot.pause(0.02)

            switcher = app.query_one("#body", ContentSwitcher)
            assert switcher.current == "dashboard-body"
            assert dash.has_focus
            app.query_one("#dashboard-goals", VerticalScroll)
            for box_id in (
                "#dashboard-task",
                "#dashboard-monitor",
                "#dashboard-capture",
                "#dashboard-checkpoints",
            ):
                app.query_one(box_id, Static)
            assert app.query_one("#dashboard-monitor", Static).border_title == "Monitor"
            assert app.query_one("#dashboard-capture", Static).border_title == "Needs capture"
            assert app.query_one("#dashboard-checkpoints", Static).border_title == "Checkpoints"
            app.query_one("#goal-1", Static)

            swarm_detail = app.query_one("#swarm-detail-content", Static)
            assert "Daemon unavailable" in _to_text(swarm_detail.content)
            assert not app.query("#dashboard-daemon")

            assert daemon_source.poll_calls[-1] == session_id

            assert dash._active_index == 1
            assert dash._following is True
            assert dash._selected_goal == 1
            assert dash._selected_task == 1

            dash.action_goal_older()
            assert dash._selected_goal == 0
            assert dash._following is False
            assert dash._selected_task == 0

            dash.action_task_next()
            assert dash._selected_task == 1
            assert dash._following is False

            repinned = DashboardModel(
                goals=[
                    _goal("First goal", [], active=False, completed=2, total=2),
                    _goal("Second goal", [], active=False, completed=2, total=2),
                    _goal(
                        "Third goal", [CompanionTask(label="T5", status="active")], active=True, completed=0, total=1
                    ),
                ],
                analysis=None,
            )
            dash.update(repinned)
            assert dash._active_index == 2
            assert dash._following is True
            assert dash._selected_goal == 2

    asyncio.run(run())
