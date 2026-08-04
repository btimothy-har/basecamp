"""Launch selected Terminal-Bench tasks with Pi and Basecamp."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from .compose import ComposeBootstrapError, resolve_docker_compose

Engine = Literal["docker", "podman"]

_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
_DEFAULT_JOBS_DIR: Final = Path.home() / "evals" / "basecamp-terminal-bench" / "jobs"
_DEFAULT_MODELS_FILE: Final = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".pi" / "agent")) / "models.json"
# Every entry is verified against the terminal-bench-2-1 manifest; harbor
# silently drops task filters that match nothing, so drift is caught by the
# manifest-snapshot test and the post-run trial reconciliation in run().
_DOCKER_AMD64_TASKS: Final = (
    "terminal-bench/hf-model-inference",
    "terminal-bench/mteb-retrieve",
    "terminal-bench/pytorch-model-recovery",
    "terminal-bench/pytorch-model-cli",
    "terminal-bench/train-fasttext",
    "terminal-bench/count-dataset-tokens",
    "terminal-bench/git-multibranch",
    "terminal-bench/sanitize-git-repo",
    "terminal-bench/git-leak-recovery",
    "terminal-bench/fix-git",
    "terminal-bench/fix-code-vulnerability",
    "terminal-bench/vulnerable-secret",
    "terminal-bench/crack-7z-hash",
    "terminal-bench/password-recovery",
    "terminal-bench/openssl-selfsigned-cert",
    "terminal-bench/nginx-request-logging",
    "terminal-bench/configure-git-webserver",
    "terminal-bench/pypi-server",
    "terminal-bench/db-wal-recovery",
    "terminal-bench/headless-terminal",
    "terminal-bench/build-cython-ext",
    "terminal-bench/compile-compcert",
    "terminal-bench/polyglot-c-py",
    "terminal-bench/polyglot-rust-c",
    "terminal-bench/modernize-scientific-stack",
    "terminal-bench/sqlite-with-gcov",
    "terminal-bench/sqlite-db-truncate",
    "terminal-bench/rstan-to-pystan",
    "terminal-bench/kv-store-grpc",
    "terminal-bench/query-optimize",
    "terminal-bench/multi-source-data-merger",
    "terminal-bench/chess-best-move",
    "terminal-bench/constraints-scheduling",
    "terminal-bench/merge-diff-arc-agi-task",
)
# Declared agent timeouts across the preset are 15 minutes for most tasks, but
# these four run 30-60. A shard's wall clock is its slowest task, so isolating
# them keeps one 60-minute ceiling from setting the whole run's duration.
_DOCKER_AMD64_LONG_TAIL: Final = (
    "terminal-bench/train-fasttext",
    "terminal-bench/compile-compcert",
    "terminal-bench/crack-7z-hash",
    "terminal-bench/mteb-retrieve",
)
# rstan-to-pystan declares 8192 MB, so two lanes can demand 16 GB on a 16 GB
# runner. It gets a shard of its own at concurrency 1 rather than taxing the
# long shard's lane count for a constraint the other slow tasks lack.
_DOCKER_AMD64_MEM: Final = ("terminal-bench/rstan-to-pystan",)
_SHORT_SHARD_COUNT: Final = 3
_DOCKER_AMD64_SHORT: Final = tuple(
    task for task in _DOCKER_AMD64_TASKS if task not in (*_DOCKER_AMD64_LONG_TAIL, *_DOCKER_AMD64_MEM)
)


def _stripe(tasks: tuple[str, ...], index: int, count: int) -> tuple[str, ...]:
    """Take every count-th task. The preset is grouped by topic, so contiguous
    slices would cluster same-flavour (and similarly slow) tasks in one shard."""
    return tasks[index::count]


_SHORT_SHARDS: Final = {
    f"docker-amd64-{index + 1}": _stripe(_DOCKER_AMD64_SHORT, index, _SHORT_SHARD_COUNT)
    for index in range(_SHORT_SHARD_COUNT)
}
_PRESETS: Final = {
    "docker-amd64": _DOCKER_AMD64_TASKS,
    "docker-amd64-long": _DOCKER_AMD64_LONG_TAIL,
    "docker-amd64-mem": _DOCKER_AMD64_MEM,
    **_SHORT_SHARDS,
    # One short, reliable task to prove the CI pipeline end to end (OpenRouter
    # canary, harbor, models file, scoring) without paying for a full run.
    "docker-smoke": ("terminal-bench/hf-model-inference",),
    "podman-smoke": ("terminal-bench/hf-model-inference",),
    "podman-arm64": (
        "terminal-bench/hf-model-inference",
        "terminal-bench/mteb-retrieve",
        "terminal-bench/pytorch-model-recovery",
    ),
    "podman-arm64-all": (
        "terminal-bench/hf-model-inference",
        "terminal-bench/mteb-leaderboard",
        "terminal-bench/mteb-retrieve",
        "terminal-bench/pytorch-model-recovery",
    ),
}


class EvalLaunchError(RuntimeError):
    """Terminal-Bench launch configuration is invalid."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"Cannot launch Terminal-Bench evaluation: {detail}")

    @classmethod
    def dirty_repository(cls) -> EvalLaunchError:
        return cls("the Basecamp worktree must be clean so HEAD identifies the evaluated source")

    @classmethod
    def missing_executable(cls, name: str) -> EvalLaunchError:
        return cls(f"required executable is unavailable: {name}")

    @classmethod
    def excessive_concurrency(cls) -> EvalLaunchError:
        return cls("concurrency cannot exceed the number of selected task attempts")

    @classmethod
    def concurrency_cap(cls, cap: int) -> EvalLaunchError:
        return cls(f"concurrency cannot exceed {cap}")

    @classmethod
    def exclusive_all(cls) -> EvalLaunchError:
        return cls("the 'all' selection cannot be combined with other tasks or presets")

    @classmethod
    def trial_mismatch(cls, expected: int, actual: int) -> EvalLaunchError:
        return cls(
            f"harbor ran {actual} trials but {expected} were requested; dataset drift silently dropped task filters"
        )

    @classmethod
    def missing_models_file(cls, path: Path) -> EvalLaunchError:
        return cls(f"models file does not exist: {path}")

    @classmethod
    def confirmation_required(cls) -> EvalLaunchError:
        return cls("paid runs require --yes; use --dry-run or --install-only first")


class PositiveIntError(argparse.ArgumentTypeError):
    """Integer argument must be positive."""

    def __init__(self) -> None:
        super().__init__("must be at least 1")


_AGENT_IMPORT_PATH: Final = "evals.terminal_bench.basecamp_pi:BasecampPiSingle"


@dataclass(frozen=True)
class LaunchOptions:
    tasks: tuple[str, ...] | None  # None selects the full dataset (no task filter)
    engine: Engine
    attempts: int
    concurrency: int
    model: str
    thinking: str
    pi_version: str
    models_file: Path | None
    jobs_dir: Path
    install_only: bool
    dry_run: bool
    confirmed: bool


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise PositiveIntError
    return parsed


def _task_name(value: str) -> str:
    return value if value.startswith("terminal-bench/") else f"terminal-bench/{value}"


def resolve_tasks(selection: Sequence[str]) -> tuple[str, ...] | None:
    values = selection or ("podman-arm64",)
    if "all" in values:
        if len(values) > 1:
            raise EvalLaunchError.exclusive_all()
        return None
    tasks: list[str] = []
    for value in values:
        expanded = _PRESETS.get(value, (_task_name(value),))
        for task in expanded:
            if task not in tasks:
                tasks.append(task)
    return tuple(tasks)


PRESET_NAMES: Final = frozenset(_PRESETS)


@dataclass(frozen=True)
class ShardProfile:
    """One CI shard: which preset it runs and the resources it is allowed."""

    label: str
    preset: str
    concurrency_cap: int | None
    timeout_minutes: int


# Timeouts: short shards hold ~10 15-minute tasks each; the long shard's four
# 30-60 minute tasks at 3 attempts and up to 3 lanes need 120-240 minutes; the
# mem shard runs its trials serially, so it gets the GitHub-hosted maximum.
_AMD64_SHARD_PROFILES: Final = (
    *(ShardProfile(str(index + 1), f"docker-amd64-{index + 1}", None, 180) for index in range(_SHORT_SHARD_COUNT)),
    ShardProfile("long", "docker-amd64-long", 3, 300),
    ShardProfile("mem", "docker-amd64-mem", 1, 360),
)
# Unsharded selections carry a whole preset in one job, so they get the
# GitHub-hosted maximum rather than a per-shard budget.
_UNSHARDED_TIMEOUT_MINUTES: Final = 360
# A smoke run exists to fail fast; its one short task fits well inside an hour.
_SMOKE_TIMEOUT_MINUTES: Final = 60


def shard_plan(task_set: str) -> tuple[ShardProfile, ...]:
    """Shard profiles covering `task_set` across parallel CI jobs.

    Only the amd64 preset is sharded; `all` passes no task filter and so cannot
    be split by preset name.
    """
    if task_set == "docker-smoke":
        return (ShardProfile(task_set, task_set, 1, _SMOKE_TIMEOUT_MINUTES),)
    if task_set != "docker-amd64":
        return (ShardProfile(task_set, task_set, None, _UNSHARDED_TIMEOUT_MINUTES),)
    return _AMD64_SHARD_PROFILES


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", nargs="*", help="Preset or task names")
    parser.add_argument("--engine", choices=("docker", "podman"), default="podman")
    parser.add_argument("--attempts", type=_positive_int, default=1)
    parser.add_argument("--concurrency", type=_positive_int, default=1)
    parser.add_argument("--model", default="openai/gpt-5.6-sol")
    parser.add_argument("--thinking", default="xhigh")
    parser.add_argument("--pi-version", default="0.80.7")
    parser.add_argument("--models-file", type=Path, default=_DEFAULT_MODELS_FILE)
    parser.add_argument("--no-models", action="store_true")
    parser.add_argument("--jobs-dir", type=Path, default=_DEFAULT_JOBS_DIR)
    parser.add_argument("--install-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Confirm a paid task run")
    return parser


def parse_options(argv: Sequence[str] | None = None) -> LaunchOptions:
    args = _build_parser().parse_args(argv)
    return LaunchOptions(
        tasks=resolve_tasks(args.selection),
        engine=args.engine,
        attempts=args.attempts,
        concurrency=args.concurrency,
        model=args.model,
        thinking=args.thinking,
        pi_version=args.pi_version,
        models_file=None if args.no_models else args.models_file.expanduser().resolve(),
        jobs_dir=args.jobs_dir.expanduser().resolve(),
        install_only=args.install_only,
        dry_run=args.dry_run,
        confirmed=args.yes,
    )


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(_REPOSITORY_ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def validate_repository(*, require_clean: bool = True) -> str:
    if require_clean and _git("status", "--porcelain"):
        raise EvalLaunchError.dirty_repository()
    return _git("rev-parse", "HEAD")


def build_harbor_command(options: LaunchOptions, commit: str) -> list[str]:
    command = [
        "harbor",
        "run",
        "--dataset",
        "terminal-bench/terminal-bench-2-1",
        "--agent",
        _AGENT_IMPORT_PATH,
        "--model",
        options.model,
        "--agent-kwarg",
        f"version={options.pi_version}",
        "--agent-kwarg",
        f"basecamp_repo={_REPOSITORY_ROOT}",
        "--agent-kwarg",
        f"basecamp_ref={commit}",
        "--agent-kwarg",
        f"thinking={options.thinking}",
    ]
    if options.models_file:
        command.extend(("--agent-kwarg", f"pi_models_file={options.models_file}"))
    if options.tasks is not None:
        for task in options.tasks:
            command.extend(("--include-task-name", task))
    command.extend(
        (
            "--n-attempts",
            str(options.attempts),
            "--n-concurrent",
            str(options.concurrency),
            "--jobs-dir",
            str(options.jobs_dir),
        )
    )
    if options.install_only:
        command.append("--install-only")
    return command


def _require_executable(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise EvalLaunchError.missing_executable(name)
    return executable


def build_environment(options: LaunchOptions) -> dict[str, str]:
    environment = dict(os.environ)
    python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(_REPOSITORY_ROOT) if not python_path else f"{_REPOSITORY_ROOT}{os.pathsep}{python_path}"
    )

    _require_executable("harbor")
    if options.engine == "docker":
        _require_executable("docker")
        return environment

    _require_executable("podman")
    environment["DOCKER_COMPOSE_BIN"] = str(resolve_docker_compose(environment))
    wrapper_dir = _REPOSITORY_ROOT / "evals" / "terminal_bench" / "bin"
    environment["PATH"] = f"{wrapper_dir}{os.pathsep}{environment['PATH']}"
    return environment


_MAX_CONCURRENCY: Final = 32


def validate_options(options: LaunchOptions) -> None:
    if options.concurrency > _MAX_CONCURRENCY:
        raise EvalLaunchError.concurrency_cap(_MAX_CONCURRENCY)
    if options.tasks is not None and options.concurrency > len(options.tasks) * options.attempts:
        raise EvalLaunchError.excessive_concurrency()
    if options.models_file and not options.models_file.is_file():
        raise EvalLaunchError.missing_models_file(options.models_file)
    if not options.install_only and not options.dry_run and not options.confirmed:
        raise EvalLaunchError.confirmation_required()


def run(options: LaunchOptions) -> int:
    validate_options(options)
    commit = validate_repository(require_clean=not options.dry_run)
    environment = build_environment(options)
    command = build_harbor_command(options, commit)

    print(f"Basecamp commit: {commit}")
    if options.tasks is None:
        print("Tasks: all (full dataset)")
    else:
        print(f"Tasks ({len(options.tasks)}):")
        for task in options.tasks:
            print(f"  - {task}")
    print(shlex.join(command))
    sys.stdout.flush()

    if options.dry_run:
        return 0
    options.jobs_dir.mkdir(parents=True, exist_ok=True)
    returncode = subprocess.run(command, cwd=_REPOSITORY_ROOT, env=environment, check=False).returncode
    if returncode == 0 and options.tasks is not None and not options.install_only:
        _reconcile_trial_count(options)
    return returncode


def _reconcile_trial_count(options: LaunchOptions) -> None:
    """Fail loudly when harbor silently dropped task filters (dataset drift)."""
    assert options.tasks is not None
    expected = len(options.tasks) * options.attempts
    job_results = sorted(
        (path for path in options.jobs_dir.glob("*/result.json") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
    )
    if not job_results:
        return
    try:
        result = json.loads(job_results[-1].read_text())
    except (OSError, json.JSONDecodeError):
        return
    actual = result.get("n_total_trials")
    if isinstance(actual, int) and actual != expected:
        raise EvalLaunchError.trial_mismatch(expected, actual)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(parse_options(argv))
    except (ComposeBootstrapError, EvalLaunchError, subprocess.CalledProcessError) as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
