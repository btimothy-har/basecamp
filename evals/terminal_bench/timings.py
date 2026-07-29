"""Render a per-task timing table from Harbor trial results.

Feeds the shard-rebalancing decision: given a directory of downloaded shard
artifacts (or a local jobs dir), it aggregates each trial's wall-clock duration
by task so shard budgets can be set from measured data instead of declared
timeouts.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class TrialTiming:
    task: str
    seconds: float


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _trial_timing(payload: dict[str, object]) -> TrialTiming | None:
    """A trial-level result carries task_name + timestamps; job-level results
    (identified by their stats/n_total_trials keys) carry neither."""
    if "stats" in payload or "n_total_trials" in payload:
        return None
    task = payload.get("task_name")
    if not isinstance(task, str) or not task:
        return None
    started = _parse_timestamp(payload.get("started_at"))
    finished = _parse_timestamp(payload.get("finished_at"))
    if started is None or finished is None or finished < started:
        return None
    return TrialTiming(task=task, seconds=(finished - started).total_seconds())


def collect_timings(root: Path) -> list[TrialTiming]:
    timings: list[TrialTiming] = []
    for path in sorted(root.rglob("result.json")):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        timing = _trial_timing(payload)
        if timing is not None:
            timings.append(timing)
    return timings


def _rows(timings: Sequence[TrialTiming]) -> Iterator[tuple[str, int, float, float, float]]:
    by_task: dict[str, list[float]] = {}
    for timing in timings:
        by_task.setdefault(timing.task, []).append(timing.seconds)
    entries = (
        (task, len(seconds), min(seconds), sum(seconds) / len(seconds), max(seconds))
        for task, seconds in by_task.items()
    )
    # Slowest first: the max trial duration is what sets a shard's wall clock.
    yield from sorted(entries, key=lambda row: row[4], reverse=True)


def build_table(timings: Sequence[TrialTiming]) -> str:
    lines = [
        "| Task | Trials | Min | Mean | Max |",
        "| --- | --- | --- | --- | --- |",
    ]
    for task, count, low, mean, high in _rows(timings):
        lines.append(f"| {task} | {count} | {_minutes(low)} | {_minutes(mean)} | {_minutes(high)} |")
    if len(lines) == 2:
        lines.append("| — | no trial timings found | | | |")
    return "\n".join(lines)


def _minutes(seconds: float) -> str:
    return f"{seconds / 60:.1f}m"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Directory containing downloaded shard artifacts or a jobs dir")
    args = parser.parse_args(argv)

    timings = collect_timings(args.root)
    print(build_table(timings))
    return 0 if timings else 1


if __name__ == "__main__":
    raise SystemExit(main())
