"""Per-task timing aggregation from Harbor trial results."""

from __future__ import annotations

import json
from pathlib import Path

from evals.terminal_bench import timings


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _trial(task: str, started: str, finished: str) -> dict:
    return {"task_name": task, "started_at": started, "finished_at": finished}


def test_collects_trial_timings_across_shard_artifacts(tmp_path: Path) -> None:
    _write(
        tmp_path / "shard-1" / "job" / "task-a__x1" / "result.json",
        _trial("terminal-bench/task-a", "2026-07-29T10:00:00Z", "2026-07-29T10:06:00Z"),
    )
    _write(
        tmp_path / "shard-2" / "job" / "task-a__x2" / "result.json",
        _trial("terminal-bench/task-a", "2026-07-29T10:00:00", "2026-07-29T10:12:00"),
    )
    _write(
        tmp_path / "shard-2" / "job" / "task-b__x1" / "result.json",
        _trial("terminal-bench/task-b", "2026-07-29T10:00:00Z", "2026-07-29T10:30:00Z"),
    )

    collected = timings.collect_timings(tmp_path)

    assert sorted((t.task, t.seconds) for t in collected) == [
        ("terminal-bench/task-a", 360.0),
        ("terminal-bench/task-a", 720.0),
        ("terminal-bench/task-b", 1800.0),
    ]


def test_job_level_results_and_malformed_trials_are_skipped(tmp_path: Path) -> None:
    _write(
        tmp_path / "job" / "result.json",
        {"n_total_trials": 3, "stats": {}, "started_at": "2026-07-29T10:00:00Z", "finished_at": "2026-07-29T11:00:00Z"},
    )
    _write(tmp_path / "job" / "task-a__x1" / "result.json", {"task_name": "terminal-bench/task-a"})
    _write(
        tmp_path / "job" / "task-b__x1" / "result.json",
        _trial("terminal-bench/task-b", "not-a-timestamp", "2026-07-29T10:05:00Z"),
    )
    _write(
        tmp_path / "job" / "task-c__x1" / "result.json",
        _trial("terminal-bench/task-c", "2026-07-29T10:10:00Z", "2026-07-29T10:00:00Z"),
    )
    (tmp_path / "job" / "task-d__x1").mkdir(parents=True)
    (tmp_path / "job" / "task-d__x1" / "result.json").write_text("not json")

    assert timings.collect_timings(tmp_path) == []


def test_table_sorts_slowest_task_first_and_reports_spread() -> None:
    rows = [
        timings.TrialTiming("terminal-bench/quick", 60.0),
        timings.TrialTiming("terminal-bench/quick", 180.0),
        timings.TrialTiming("terminal-bench/slow", 3600.0),
    ]

    table = timings.build_table(rows)

    lines = table.splitlines()
    assert lines[2] == "| terminal-bench/slow | 1 | 60.0m | 60.0m | 60.0m |"
    assert lines[3] == "| terminal-bench/quick | 2 | 1.0m | 2.0m | 3.0m |"


def test_empty_input_renders_a_placeholder_and_fails_the_cli(tmp_path: Path, capsys) -> None:
    assert timings.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "no trial timings found" in out
