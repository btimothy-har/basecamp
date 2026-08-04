"""Resolve GitHub Actions inputs into a Terminal-Bench eval job matrix.

Emitted as `key=value` lines for `$GITHUB_OUTPUT`. This lives in Python rather
than inline shell because the matrix is a cross product of model legs and task
shards, and because the validation below is worth testing.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from .run import PRESET_NAMES, ShardProfile, resolve_tasks, shard_plan

# Each leg carries a slug because artifact names disallow "/".
_MODELS: Final = {
    "glm-5.2": "openrouter/z-ai/glm-5.2",
    "kimi-k3": "openrouter/moonshotai/kimi-k3",
    "qwen3.8-max": "openrouter/qwen/qwen3.8-max",
    "deepseek-v4-pro": "openrouter/deepseek/deepseek-v4-pro",
    # Pinned snapshot, not the rolling deepseek-v4-flash alias: an eval leg has
    # to name the exact weights it scored.
    "deepseek-v4-flash-0731": "openrouter/deepseek/deepseek-v4-flash-0731",
    # Frontier legs, also via OpenRouter so the whole matrix keeps one credential
    # and one canary. Neither vendor publishes dated snapshots here, so these four
    # name rolling aliases and a score cannot pin the weights the way the DeepSeek
    # Flash leg does.
    "gpt-5.6-terra": "openrouter/openai/gpt-5.6-terra",
    "gpt-5.6-sol": "openrouter/openai/gpt-5.6-sol",
    "opus-5": "openrouter/anthropic/claude-opus-5",
    "opus-4.8": "openrouter/anthropic/claude-opus-4.8",
}
# One level per model, keyed so a leg can diverge; every leg runs at xhigh. For
# the open-weight legs that is already the provider's ceiling (their maps top out
# by sending "max"), while the Anthropic/OpenAI legs expose a further "max" above
# xhigh. They stay at xhigh deliberately: both vendors name xhigh as the setting
# for coding and agentic work and warn that max overthinks, and these tasks run in
# CPU-capped containers where extra reasoning buys wall clock against the agent
# timeout. Reach max through the workflow's thinking override to A/B it.
_DEFAULT_THINKING: Final = dict.fromkeys(_MODELS, "xhigh")
_ALL_MODELS: Final = "all"
_PER_MODEL: Final = "per-model"
_PI_VERSION_PATTERN: Final = re.compile(r"\d+\.\d+\.\d+")


class MatrixInputError(ValueError):
    """Workflow inputs cannot be resolved into a matrix."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"Cannot build Terminal-Bench eval matrix: {detail}")

    @classmethod
    def not_positive(cls, name: str, value: str) -> MatrixInputError:
        return cls(f"{name} must be a positive integer: {value!r}")

    @classmethod
    def unknown_models(cls, value: str) -> MatrixInputError:
        return cls(f"unknown models input: {value!r}")

    @classmethod
    def unknown_task_set(cls, value: str) -> MatrixInputError:
        return cls(f"unknown task-set input: {value!r}")

    @classmethod
    def bad_pi_version(cls, value: str) -> MatrixInputError:
        return cls(f"pi-version must be x.y.z: {value!r}")


def _positive_int(name: str, value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise MatrixInputError.not_positive(name, value)
    return int(value)


def _model_slugs(models: str) -> tuple[str, ...]:
    if models == _ALL_MODELS:
        return tuple(_MODELS)
    if models in _MODELS:
        return (models,)
    raise MatrixInputError.unknown_models(models)


def _shard_concurrency(profile: ShardProfile, requested: int, attempts: int) -> int:
    """Lanes for one shard: the profile's cap first, then never above what the
    shard can actually fill.

    A shard holds a fraction of the preset, so the launcher's
    concurrency-versus-trials check would reject a request sized for the whole
    preset.
    """
    lanes = requested if profile.concurrency_cap is None else min(requested, profile.concurrency_cap)
    tasks = resolve_tasks((profile.preset,))
    if tasks is not None:
        lanes = min(lanes, len(tasks) * attempts)
    return lanes


def build_matrix(
    *,
    models: str,
    task_set: str,
    attempts: str,
    concurrency: str,
    thinking: str,
    pi_version: str,
) -> dict[str, str]:
    attempt_count = _positive_int("attempts", attempts)
    lane_count = _positive_int("concurrency", concurrency)
    # fullmatch, not match: a trailing newline in the input would otherwise
    # pass validation and corrupt the $GITHUB_OUTPUT key=value line.
    if not _PI_VERSION_PATTERN.fullmatch(pi_version):
        raise MatrixInputError.bad_pi_version(pi_version)
    # A typo would otherwise only fail after OpenRouter/docker/harbor setup, when
    # the launcher treats the unknown name as a single task filter.
    if task_set != "all" and task_set not in PRESET_NAMES:
        raise MatrixInputError.unknown_task_set(task_set)

    include = [
        {
            "model": _MODELS[slug],
            "slug": slug,
            "thinking": _DEFAULT_THINKING[slug] if thinking == _PER_MODEL else thinking,
            "shard": profile.label,
            "preset": profile.preset,
            "concurrency": _shard_concurrency(profile, lane_count, attempt_count),
            "timeout": profile.timeout_minutes,
        }
        for slug in _model_slugs(models)
        for profile in shard_plan(task_set)
    ]
    return {
        "matrix": json.dumps({"include": include}, separators=(",", ":")),
        "attempts": str(attempt_count),
        "pi-version": pi_version,
        "shard-count": str(len(include)),
        "config": f"{task_set} x{attempt_count} attempts, requested concurrency {lane_count}, pi {pi_version}",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("models", "task-set", "attempts", "concurrency", "thinking", "pi-version"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--output", type=Path, help="Append key=value lines here instead of stdout")
    args = parser.parse_args(argv)

    outputs = build_matrix(
        models=args.models,
        task_set=args.task_set,
        attempts=args.attempts,
        concurrency=args.concurrency,
        thinking=args.thinking,
        pi_version=args.pi_version,
    )
    rendered = "".join(f"{key}={value}\n" for key, value in outputs.items())
    if args.output:
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
