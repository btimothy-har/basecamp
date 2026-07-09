"""Tests for the merged, mtime-watched dashboard source."""

from __future__ import annotations

import json
from pathlib import Path

from basecamp.companion.source import DashboardModel, DashboardSource


def _write_tasks(path: Path, goals: list[dict]) -> None:
    path.write_text(json.dumps(goals), encoding="utf-8")


def _write_analysis(path: Path, monitor: list[str]) -> None:
    path.write_text(
        json.dumps({"version": 2, "sessionId": "s", "updatedAt": "t", "monitor": monitor}),
        encoding="utf-8",
    )


def test_poll_returns_none_when_nothing_present_after_first_poll(tmp_path: Path) -> None:
    source = DashboardSource(tmp_path / "tasks.json", tmp_path / "a.analysis.json")
    first = source.poll()
    assert isinstance(first, DashboardModel)
    assert first.goals == []
    assert first.analysis is None
    assert source.poll() is None


def test_poll_merges_goals_and_analysis(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.json"
    analysis = tmp_path / "a.analysis.json"
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
    _write_analysis(analysis, ["monitor1"])

    model = DashboardSource(tasks, analysis).poll()
    assert model is not None
    assert len(model.goals) == 1
    assert model.goals[0].goal == "G"
    assert model.analysis is not None
    assert model.analysis.monitor == ["monitor1"]


def test_poll_maps_v1_analysis_for_compatibility(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.json"
    analysis = tmp_path / "a.analysis.json"
    _write_tasks(tasks, [])
    analysis.write_text(
        json.dumps(
            {
                "version": 1,
                "sessionId": "s",
                "updatedAt": "t",
                "decisions": ["legacy monitor"],
                "openItems": ["legacy capture"],
                "warnings": ["legacy checkpoint"],
            }
        ),
        encoding="utf-8",
    )

    model = DashboardSource(tasks, analysis).poll()

    assert model is not None
    assert model.analysis is not None
    assert model.analysis.monitor == ["legacy monitor"]
    assert model.analysis.needs_capture == ["legacy capture"]
    assert model.analysis.checkpoints == ["legacy checkpoint"]


def test_poll_detects_analysis_change_keeping_goals(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.json"
    analysis = tmp_path / "a.analysis.json"
    _write_tasks(tasks, [{"goal": "G", "tasks": [], "active": True, "archivedAt": None}])
    _write_analysis(analysis, ["monitor1"])
    source = DashboardSource(tasks, analysis)
    source.poll()
    assert source.poll() is None

    _write_analysis(analysis, ["monitor2"])
    model = source.poll()
    assert model is not None
    assert model.analysis is not None
    assert model.analysis.monitor == ["monitor2"]
    assert len(model.goals) == 1
