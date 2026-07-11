"""Tests for the merged dashboard source (goal-cycle file + daemon analysis fetch)."""

from __future__ import annotations

import json
from pathlib import Path

from basecamp.companion.analysis import CompanionAnalysis
from basecamp.companion.source import DashboardModel, DashboardSource


def _write_tasks(path: Path, goals: list[dict]) -> None:
    path.write_text(json.dumps(goals), encoding="utf-8")


def test_poll_returns_none_when_nothing_present_after_first_poll(tmp_path: Path) -> None:
    source = DashboardSource(tmp_path / "tasks.json", lambda: None)
    first = source.poll()
    assert isinstance(first, DashboardModel)
    assert first.goals == []
    assert first.analysis is None
    assert source.poll() is None


def test_poll_merges_goals_and_daemon_analysis(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.json"
    _write_tasks(
        tasks,
        [
            {
                "goal": "G",
                "tasks": [{"label": "T", "status": "active", "notes": None}],
                "active": True,
                "archivedAt": None,
            }
        ],
    )

    model = DashboardSource(tasks, lambda: CompanionAnalysis(monitor=["monitor1"])).poll()

    assert model is not None
    assert len(model.goals) == 1
    assert model.goals[0].goal == "G"
    assert model.analysis is not None
    assert model.analysis.monitor == ["monitor1"]


def test_poll_detects_analysis_change_keeping_goals(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.json"
    _write_tasks(tasks, [{"goal": "G", "tasks": [], "active": True, "archivedAt": None}])

    current: dict[str, CompanionAnalysis | None] = {"analysis": CompanionAnalysis(monitor=["monitor1"])}
    source = DashboardSource(tasks, lambda: current["analysis"])
    source.poll()
    assert source.poll() is None  # unchanged fetch → no re-render

    current["analysis"] = CompanionAnalysis(monitor=["monitor2"])
    model = source.poll()

    assert model is not None
    assert model.analysis is not None
    assert model.analysis.monitor == ["monitor2"]
    assert len(model.goals) == 1


def test_poll_keeps_last_analysis_when_fetch_returns_none(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.json"
    _write_tasks(tasks, [])
    current: dict[str, CompanionAnalysis | None] = {"analysis": CompanionAnalysis(monitor=["m"])}
    source = DashboardSource(tasks, lambda: current["analysis"])
    source.poll()  # populates analysis = ["m"]

    current["analysis"] = None  # daemon down / blip — must NOT clear the panel
    assert source.poll() is None  # None is ignored → no change → no re-render

    # Re-serving the same value proves the None never cleared it: unchanged → still None.
    current["analysis"] = CompanionAnalysis(monitor=["m"])
    assert source.poll() is None
