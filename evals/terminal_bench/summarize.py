"""Render a Markdown summary of the newest Harbor job result."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

_TRIAL_COUNT_KEYS: Final = (
    "n_completed_trials",
    "n_errored_trials",
    "n_pending_trials",
    "n_running_trials",
    "n_cancelled_trials",
)


def find_job_result(jobs_dir: Path) -> Path | None:
    """Return the newest job-level result.json (depth 1; trial files live deeper)."""
    candidates = sorted(
        (path for path in jobs_dir.glob("*/result.json") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def build_summary(result: dict[str, Any], source: Path) -> tuple[list[str], bool]:
    stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
    evals = stats.get("evals") if isinstance(stats.get("evals"), dict) else {}

    lines = ["## Terminal-Bench results", "", f"Source: `{source.name}`", ""]
    lines.append("| Eval | Score |")
    lines.append("| --- | --- |")
    scores = 0
    for name, entry in sorted(evals.items()):
        metrics = entry.get("metrics") if isinstance(entry, dict) else None
        if isinstance(metrics, list):
            for metric in metrics:
                if isinstance(metric, dict) and "mean" in metric:
                    lines.append(f"| {name} | {metric['mean']:.4f} |")
                    scores += 1
    if scores == 0:
        lines.append("| — | no metrics recorded |")

    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| n_total_trials | {result.get('n_total_trials', '?')} |")
    lines.extend(f"| {key} | {stats[key]} |" for key in _TRIAL_COUNT_KEYS if key in stats)
    if "cost_usd" in stats:
        lines.append(f"| cost_usd | {stats['cost_usd']:.4f} |")

    incomplete = sum(
        int(stats.get(key, 0) or 0) for key in ("n_pending_trials", "n_running_trials", "n_cancelled_trials")
    )
    if incomplete:
        lines.append("")
        lines.append(f"⚠️ Job is incomplete: {incomplete} trial(s) pending, running, or cancelled.")
    return lines, incomplete == 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs_dir", type=Path)
    args = parser.parse_args(argv)

    jobs_dir = args.jobs_dir.expanduser()
    result_path = find_job_result(jobs_dir) if jobs_dir.is_dir() else None
    if result_path is None:
        print("## Terminal-Bench results\n\nNo job-level result.json found.")
        return 1
    try:
        result = json.loads(result_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"## Terminal-Bench results\n\nCould not parse {result_path}: {exc}")
        return 1

    lines, complete = build_summary(result, result_path)
    print("\n".join(lines))
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
