"""Tests for the analysis-only companion dashboard and app daemon polling."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from rich.console import Console
from textual.app import App, ComposeResult
from textual.widgets import Static

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
from basecamp.companion.ui.dashboard import DashboardBody


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


def _write_snapshot(path: Path, session_id: str, cwd: Path) -> None:
    path.write_text(
        json.dumps({"version": 1, "sessionId": session_id, "updatedAt": "t", "effectiveCwd": str(cwd)}),
        encoding="utf-8",
    )


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

    def poll_messages(self, root_id: str, agent_handle: str, limit: int | None = None) -> DaemonAgentMessages:
        self.message_poll_calls.append((root_id, agent_handle, limit))
        assert limit is None or isinstance(limit, int)
        return self.messages or DaemonAgentMessagesOk(root_id=root_id, agent_handle=agent_handle, messages=[])


class _DaemonPollError(Exception):
    def __init__(self, root_id: str) -> None:
        super().__init__(f"daemon failed for {root_id}")


class _FailingDaemonSource:
    def poll(self, root_id: str) -> DaemonSummary:
        raise _DaemonPollError(root_id)


class _DashboardHostApp(App[None]):
    def __init__(self, dashboard: DashboardBody) -> None:
        super().__init__()
        self._dashboard = dashboard

    def compose(self) -> ComposeResult:
        yield self._dashboard


def _daemon_summary_ok(*, total: int, agents: list[DaemonSummaryAgent]) -> DaemonSummaryOk:
    return DaemonSummaryOk(
        root_id="root",
        counts=DaemonSummaryCounts(pending=0, running=0, completed=total, failed=0, total=total),
        agents=agents,
        session_active=True,
    )


def _running_agent(handle: str, session_name: str, agent_type: str) -> DaemonSummaryAgent:
    return DaemonSummaryAgent(
        agent_handle=handle,
        agent_type=agent_type,
        role="worker",
        session_name=session_name,
        status="running",
        result_preview=None,
        error_preview=None,
        exit_code=None,
        created_at="2026-01-01T00:00:00Z",
        started_at="2026-01-01T00:00:01Z",
        ended_at=None,
    )


def test_poll_daemon_summary_converts_unexpected_source_errors(tmp_path: Path) -> None:
    app = CompanionApp(
        snapshot_path=tmp_path / "snapshot.json",
        cwd=tmp_path,
        daemon_source=_FailingDaemonSource(),
    )

    result = app._poll_daemon_summary("session-123")

    assert isinstance(result, DaemonSummaryError)
    assert "session-123" in result.error


def test_dashboard_renders_daemon_analysis(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _build_repo(repo)
    snapshot_path = tmp_path / "snapshot.json"
    session_id = "abcd-1234-5678-90ef"
    _write_snapshot(snapshot_path, session_id, repo)
    daemon_source = _FakeDaemonSource(
        DaemonSummaryUnavailable(error="unavailable in test"),
        analysis=CompanionAnalysis(
            monitor=["watch the tests"],
            needs_capture=["capture a decision"],
            checkpoints=["checkpoint one"],
        ),
    )
    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo, daemon_source=daemon_source)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            dash = app.query_one("#dashboard-body", DashboardBody)

            assert app.query_one("#dashboard-monitor", Static).border_title == "Monitor"
            assert app.query_one("#dashboard-capture", Static).border_title == "Needs capture"
            assert app.query_one("#dashboard-checkpoints", Static).border_title == "Checkpoints"
            assert not app.query("#dashboard-goals")
            assert not app.query("#dashboard-task")

            for _ in range(100):
                if dash._analysis is not None:
                    break
                await pilot.pause(0.02)
            else:
                raise AssertionError

            assert "watch the tests" in _to_text(app.query_one("#dashboard-monitor", Static).content)
            assert "capture a decision" in _to_text(app.query_one("#dashboard-capture", Static).content)
            assert "checkpoint one" in _to_text(app.query_one("#dashboard-checkpoints", Static).content)
            assert daemon_source.poll_calls[-1] == session_id

    asyncio.run(run())


def test_dashboard_update_retains_last_analysis_on_none() -> None:
    dashboard = DashboardBody()
    app = _DashboardHostApp(dashboard)
    analysis = CompanionAnalysis(monitor=["keep me"], needs_capture=[], checkpoints=[])

    async def run() -> None:
        async with app.run_test():
            dashboard.update(analysis)
            assert dashboard._analysis is analysis

            dashboard.update(None)
            assert dashboard._analysis is analysis
            assert "keep me" in _to_text(app.query_one("#dashboard-monitor", Static).content)

    asyncio.run(run())


def test_swarm_receives_daemon_summary_when_session_active(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    session_id = "dead-beef-cafe-babe"
    _write_snapshot(snapshot_path, session_id, repo)
    daemon_source = _FakeDaemonSource(_daemon_summary_ok(total=0, agents=[]))
    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo, daemon_source=daemon_source)

    async def run() -> None:
        async with app.run_test() as pilot:
            for _ in range(100):
                if daemon_source.poll_calls:
                    break
                await pilot.pause(0.02)
            else:
                raise AssertionError

            swarm_detail = app.query_one("#swarm-detail-content", Static)
            assert "No async agents yet" in _to_text(swarm_detail.content)
            assert daemon_source.poll_calls[-1] == session_id

    asyncio.run(run())


def test_swarm_polls_messages_for_selected_agent_when_session_active(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    session_id = "feed-beef-cafe-babe"
    _write_snapshot(snapshot_path, session_id, repo)
    daemon_source = _FakeDaemonSource(
        _daemon_summary_ok(
            total=2,
            agents=[
                _running_agent("selected-agent", "selected", "worker"),
                _running_agent("other-agent", "other", "scout"),
            ],
        )
    )
    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo, daemon_source=daemon_source)

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
