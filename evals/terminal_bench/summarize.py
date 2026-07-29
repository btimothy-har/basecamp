"""Render a Markdown summary of Harbor job results, per job or pooled across shards."""

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
# Harbor counts errored trials as completed, and the verifier still scores most
# of them (an agent crash usually earns a 0.0 reward bucket entry). Errored is
# therefore an ordinary capability outcome, not an incompleteness signal; the
# real gap is a trial with no reward bucket entry at all.
_ERRORED_NOTE: Final = "errored trials that were scored count toward the mean at their (usually zero) reward"
_UNSCORED_NOTE: Final = "finished without a score; the mean excludes them"


def find_job_result(jobs_dir: Path) -> Path | None:
    """Return the newest job-level result.json (depth 1; trial files live deeper)."""
    candidates = sorted(
        (path for path in jobs_dir.glob("*/result.json") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def _scored_rewards(entry: object) -> tuple[float, int]:
    """(reward total, scored trial count) from one eval entry's reward buckets.

    Defensive by design: `reward_stats` may be null, bucket keys may be
    non-numeric, and bucket values may be non-lists. Malformed pieces are
    skipped — the coverage gate then reports their trials as unscored instead
    of crashing the summary.
    """
    if not isinstance(entry, dict):
        return 0.0, 0
    reward_stats = entry.get("reward_stats")
    buckets = reward_stats.get("reward") if isinstance(reward_stats, dict) else None
    if not isinstance(buckets, dict):
        return 0.0, 0
    total = 0.0
    scored = 0
    for reward, trials in buckets.items():
        if not isinstance(trials, list):
            continue
        try:
            value = float(reward)
        except (TypeError, ValueError):
            continue
        total += value * len(trials)
        scored += len(trials)
    return total, scored


def build_summary(result: dict[str, Any], source: Path) -> tuple[list[str], bool]:
    stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
    evals = stats.get("evals") if isinstance(stats.get("evals"), dict) else {}
    n_total = int(result.get("n_total_trials", 0) or 0)

    lines = ["## Terminal-Bench results", "", f"Source: `{source.name}`", ""]
    lines.append("| Eval | Score |")
    lines.append("| --- | --- |")
    scores = 0
    n_scored = 0
    for name, entry in sorted(evals.items()):
        n_scored += _scored_rewards(entry)[1]
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
    lines.append(f"| n_scored_trials | {n_scored} |")
    lines.extend(f"| {key} | {stats[key]} |" for key in _TRIAL_COUNT_KEYS if key in stats)
    if "cost_usd" in stats:
        lines.append(f"| cost_usd | {stats['cost_usd']:.4f} |")

    incomplete = sum(
        int(stats.get(key, 0) or 0) for key in ("n_pending_trials", "n_running_trials", "n_cancelled_trials")
    )
    errored = int(stats.get("n_errored_trials", 0) or 0)
    unscored = n_total - n_scored
    if incomplete:
        lines.append("")
        lines.append(f"⚠️ Job is incomplete: {incomplete} trial(s) pending, running, or cancelled.")
    if errored:
        lines.append("")
        lines.append(f"⚠️ Job has {errored} errored trial(s); {_ERRORED_NOTE}.")
    if unscored > 0:
        lines.append("")
        lines.append(f"⚠️ {unscored} trial(s) {_UNSCORED_NOTE}.")
    return lines, incomplete == 0 and n_scored == n_total


def _is_job_result(payload: object) -> bool:
    """Trial-level result.json files sit beside job-level ones in the artifact
    tree and carry neither key, so this discriminates without depending on depth."""
    return isinstance(payload, dict) and "stats" in payload and "n_total_trials" in payload


def find_shard_results(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Every job-level result under `root`, one per downloaded shard artifact."""
    found: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(root.rglob("result.json")):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if _is_job_result(payload):
            found.append((path, payload))
    return found


def pool_results(results: Sequence[tuple[Path, dict[str, Any]]]) -> dict[str, Any]:
    """Combine shard results into per-eval-key scores weighted by trial count.

    Averaging the shards' own means would be wrong whenever shards hold
    different numbers of tasks, so the reward buckets are re-pooled instead.
    Scores are grouped by eval key because the key embeds the model: pooling
    across keys would blend both model legs into one unattributable number.
    """
    counts = dict.fromkeys(_TRIAL_COUNT_KEYS, 0)
    cost = 0.0
    total_trials = 0
    per_eval: dict[str, dict[str, Any]] = {}
    for _, result in results:
        stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
        total_trials += int(result.get("n_total_trials", 0) or 0)
        cost += float(stats.get("cost_usd", 0) or 0)
        for key in _TRIAL_COUNT_KEYS:
            counts[key] += int(stats.get(key, 0) or 0)
        evals = stats.get("evals") if isinstance(stats.get("evals"), dict) else {}
        for name, entry in evals.items():
            reward_total, scored = _scored_rewards(entry)
            aggregate = per_eval.setdefault(name, {"reward_total": 0.0, "n_scored": 0})
            aggregate["reward_total"] += reward_total
            aggregate["n_scored"] += scored
    return {
        "evals": {
            name: {
                "score": aggregate["reward_total"] / aggregate["n_scored"] if aggregate["n_scored"] else None,
                "n_scored": aggregate["n_scored"],
            }
            for name, aggregate in sorted(per_eval.items())
        },
        "n_total_trials": total_trials,
        "n_scored_trials": sum(aggregate["n_scored"] for aggregate in per_eval.values()),
        "cost_usd": cost,
        **counts,
    }


def build_pooled_summary(
    pooled: dict[str, Any],
    shards: int,
    expected_shards: int | None = None,
) -> tuple[list[str], bool]:
    expectation = "" if expected_shards is None else f" (expected {expected_shards})"
    lines = [
        "## Terminal-Bench pooled results",
        "",
        f"Shards: {shards}{expectation}",
        "",
        "| Eval | Score | Scored trials |",
        "| --- | --- | --- |",
    ]
    scores = 0
    for name, entry in pooled["evals"].items():
        score = entry["score"]
        if score is not None:
            scores += 1
        lines.append(f"| {name} | {'—' if score is None else f'{score:.4f}'} | {entry['n_scored']} |")
    if not pooled["evals"]:
        lines.append("| — | no rewards recorded | — |")

    lines.extend(
        (
            "",
            "| Metric | Value |",
            "| --- | --- |",
            f"| n_scored_trials | {pooled['n_scored_trials']} |",
            f"| n_total_trials | {pooled['n_total_trials']} |",
        )
    )
    lines.extend(f"| {key} | {pooled[key]} |" for key in _TRIAL_COUNT_KEYS)
    lines.append(f"| cost_usd | {pooled['cost_usd']:.4f} |")

    incomplete = sum(pooled[key] for key in ("n_pending_trials", "n_running_trials", "n_cancelled_trials"))
    errored = pooled["n_errored_trials"]
    unscored = pooled["n_total_trials"] - pooled["n_scored_trials"]
    shards_ok = expected_shards is None or shards == expected_shards
    if not shards_ok:
        lines.extend(("", f"⚠️ Expected {expected_shards} shard result(s) but found {shards}; a shard is missing."))
    if incomplete:
        lines.extend(("", f"⚠️ {incomplete} trial(s) pending, running, or cancelled across shards."))
    if errored:
        lines.extend(("", f"⚠️ {errored} errored trial(s) across shards; {_ERRORED_NOTE}."))
    if unscored > 0:
        lines.extend(("", f"⚠️ {unscored} trial(s) {_UNSCORED_NOTE}."))
    complete = shards_ok and incomplete == 0 and pooled["n_scored_trials"] == pooled["n_total_trials"] and scores > 0
    return lines, complete


def _summarize_pooled(root: Path, expected_shards: int | None) -> int:
    results = find_shard_results(root) if root.is_dir() else []
    if not results:
        print("## Terminal-Bench pooled results\n\nNo job-level result.json found.")
        return 1
    lines, complete = build_pooled_summary(pool_results(results), len(results), expected_shards)
    print("\n".join(lines))
    return 0 if complete else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs_dir", type=Path)
    parser.add_argument(
        "--pooled",
        action="store_true",
        help="Treat jobs_dir as a tree of shard artifacts and pool them into per-eval scores",
    )
    parser.add_argument(
        "--expected-shards",
        type=int,
        default=None,
        help="Fail the pooled summary unless exactly this many shard results were found",
    )
    args = parser.parse_args(argv)

    jobs_dir = args.jobs_dir.expanduser()
    if args.pooled:
        return _summarize_pooled(jobs_dir, args.expected_shards)

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
