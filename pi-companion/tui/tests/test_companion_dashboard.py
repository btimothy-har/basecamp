"""Tests for the goal-centric companion dashboard."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from companion_tui.analysis import companion_analysis_path
from companion_tui.app import (
    CompanionApp,
    DashboardBody,
    SwarmBody,
    _format_duration,
    _goal_panel,
    _render_bullets,
    _render_daemon_summary,
    _render_task_detail,
    _truncate_preview,
    next_body_mode,
)
from companion_tui.daemon import (
    DaemonSummary,
    DaemonSummaryAgent,
    DaemonSummaryCounts,
    DaemonSummaryError,
    DaemonSummaryOk,
    DaemonSummaryUnavailable,
)
from companion_tui.snapshot import CompanionGoal, CompanionProgress, CompanionTask
from companion_tui.source import DashboardModel
from rich.console import Console
from textual.containers import VerticalScroll
from textual.widgets import ContentSwitcher, Static


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
    def __init__(self, summary: DaemonSummary | None) -> None:
        self.summary = summary
        self.poll_calls: list[str] = []

    def poll(self, root_id: str, limit: int | None = None) -> DaemonSummary | None:
        self.poll_calls.append(root_id)
        assert limit is None or isinstance(limit, int)
        return self.summary


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


def test_render_bullets_empty_shows_dash() -> None:
    assert _render_bullets([]).plain == "—"


def test_render_bullets_populated() -> None:
    plain = _render_bullets(["first", "second"]).plain
    assert "• first" in plain
    assert "• second" in plain


def test_truncate_preview_collapses_newlines_and_respects_limit() -> None:
    assert _truncate_preview("one\ntwo", max_length=20) == "one two"
    assert _truncate_preview("abcdef", max_length=4) == "abc…"


def test_format_duration_boundaries() -> None:
    assert _format_duration(59) == "59s"
    assert _format_duration(60) == "1m"
    assert _format_duration(3661) == "1h 1m"


def test_render_daemon_summary_none_is_empty() -> None:
    assert _render_daemon_summary(None).plain == ""


def test_render_daemon_summary_empty_ok_shows_no_async_agents() -> None:
    summary = _daemon_summary_ok(total=0, agents=[])
    assert "No async agents yet" in _to_text(_render_daemon_summary(summary))


def test_render_daemon_summary_unavailable() -> None:
    summary = DaemonSummaryUnavailable(error="daemon socket missing")
    text = _to_text(_render_daemon_summary(summary))
    assert "Daemon unavailable" in text
    assert "daemon socket missing" in text


def test_render_daemon_summary_error() -> None:
    summary = DaemonSummaryError(error="bad daemon payload")
    text = _to_text(_render_daemon_summary(summary))
    assert "Daemon error" in text
    assert "bad daemon payload" in text


def test_render_daemon_summary_running_uses_hourglass() -> None:
    summary = _daemon_summary_ok(
        total=1,
        agents=[
            DaemonSummaryAgent(
                agent_handle="worker-mossy-otter",
                agent_type="worker",
                role="agent",
                session_name="worker",
                status="running",
                result_preview=None,
                error_preview=None,
                exit_code=None,
                created_at="2099-01-01T00:00:00Z",
                started_at="2099-01-01T00:00:00Z",
                ended_at=None,
            )
        ],
    )
    text = _to_text(_render_daemon_summary(summary))
    assert "⏳" in text
    assert "running" in text


def test_render_daemon_summary_populated() -> None:
    summary = _daemon_summary_ok(
        total=2,
        agents=[
            DaemonSummaryAgent(
                agent_handle="scout-mossy-otter",
                agent_type="scout",
                role="agent",
                session_name="scout",
                status="completed",
                result_preview="all good",
                error_preview=None,
                exit_code=0,
                created_at="2026-01-01T00:00:00Z",
                started_at="2026-01-01T00:00:01Z",
                ended_at="2026-01-01T00:00:03Z",
            ),
            DaemonSummaryAgent(
                agent_handle="worker-brisk-lynx",
                agent_type="worker",
                role="agent",
                session_name="worker",
                status="failed",
                result_preview=None,
                error_preview="boom",
                exit_code=1,
                created_at="2026-01-01T00:00:00Z",
                started_at="2026-01-01T00:00:04Z",
                ended_at="2026-01-01T00:00:04Z",
            ),
        ],
    )
    text = _to_text(_render_daemon_summary(summary))
    assert "scout" in text
    assert "worker" in text
    assert "scout-mossy-otter" not in text
    assert "worker-brisk-lynx" not in text
    assert "completed" in text
    assert "failed" in text
    assert "all good" in text
    assert "boom" in text


def test_dashboard_css_uses_requested_row_ratios() -> None:
    css = CompanionApp.CSS
    assert "#dashboard-task {\n        height: 3fr;" in css
    assert "#dashboard-decisions {\n        height: 2fr;" in css
    assert "#dashboard-bottom {\n        height: 2fr;" in css
    assert "#dashboard-daemon" not in css


def test_swarm_css_includes_two_panel_layout() -> None:
    css = CompanionApp.CSS
    assert "#swarm-body" in css
    assert "#swarm-agents" in css
    assert "#swarm-detail" in css
    assert "#swarm-daemon" not in css


def test_render_bullets_preserves_literal_markup_text() -> None:
    assert "[bold]x[/]" in _render_bullets(["[bold]x[/]"]).plain


def test_goal_panel_marks_active_and_shows_progress() -> None:
    goal = _goal("Second goal", [], active=True, completed=0, total=2)
    text = _to_text(_goal_panel(goal, is_selected=True, is_active=True))
    assert "Second goal" in text
    assert "active" in text
    assert "0/2" in text


def test_goal_panel_preserves_literal_markup() -> None:
    goal = _goal("[bold]x[/]", [], active=False, completed=0, total=0)
    assert "[bold]x[/]" in _to_text(_goal_panel(goal, is_selected=False, is_active=False))


def test_render_task_detail_empty() -> None:
    assert "No tasks" in _to_text(_render_task_detail(None, 0))
    assert "No tasks" in _to_text(_render_task_detail(_goal("g", [], active=True, completed=0, total=0), 0))


def test_render_task_detail_shows_header_and_faded_annotation() -> None:
    goal = _goal(
        "g",
        [
            CompanionTask(label="T1", status="completed", description="d1", criteria="c1", notes=None),
            CompanionTask(label="T2", status="active", description="desc two", criteria="c2", notes="a note"),
        ],
        active=True,
        completed=1,
        total=2,
    )
    text = _to_text(_render_task_detail(goal, 1))
    assert "[2/2]" in text
    assert "T2" in text
    assert "desc two" in text
    assert "a note" in text
    assert "note" in text


def test_next_body_mode_cycles_through_dashboard_diff_files_swarm() -> None:
    assert next_body_mode("dashboard-body") == "diff-body"
    assert next_body_mode("diff-body") == "files-body"
    assert next_body_mode("files-body") == "swarm-body"
    assert next_body_mode("swarm-body") == "dashboard-body"


def test_pinned_task_index_prefers_active() -> None:
    goal = _goal(
        "g",
        [
            CompanionTask(label="A", status="completed"),
            CompanionTask(label="B", status="active"),
            CompanionTask(label="C", status="pending"),
        ],
        active=True,
        completed=1,
        total=3,
    )
    assert DashboardBody._pinned_task_index(goal) == 1


def test_pinned_task_index_falls_back_to_last_when_all_completed() -> None:
    goal = _goal(
        "g",
        [CompanionTask(label="A", status="completed"), CompanionTask(label="B", status="completed")],
        active=False,
        completed=2,
        total=2,
    )
    assert DashboardBody._pinned_task_index(goal) == 1


def test_pinned_task_index_empty_goal_is_zero() -> None:
    assert DashboardBody._pinned_task_index(_goal("g", [], active=True, completed=0, total=0)) == 0


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
    analysis_path = companion_analysis_path(session_id, snapshot_path.parent)
    analysis_path.write_text(
        json.dumps(
            {
                "version": 1,
                "sessionId": session_id,
                "updatedAt": "t",
                "decisions": [],
                "openItems": [],
                "warnings": [],
            }
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
                    "agentMode": "executor",
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
    analysis_path = companion_analysis_path(session_id, snapshot_path.parent)
    analysis_path.write_text(
        json.dumps(
            {
                "version": 1,
                "sessionId": session_id,
                "updatedAt": "t",
                "decisions": ["dec1"],
                "openItems": ["open1"],
                "warnings": ["warn1"],
            }
        ),
        encoding="utf-8",
    )

    daemon_source = _FakeDaemonSource(DaemonSummaryUnavailable(error="unavailable in test"))
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
                "#dashboard-decisions",
                "#dashboard-open",
                "#dashboard-warnings",
            ):
                app.query_one(box_id, Static)
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
