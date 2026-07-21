"""Launch selected Terminal-Bench tasks with Pi and Basecamp."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

Engine = Literal["docker", "podman"]

_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
_DEFAULT_JOBS_DIR: Final = Path.home() / "evals" / "basecamp-terminal-bench" / "jobs"
_DEFAULT_MODELS_FILE: Final = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".pi" / "agent")) / "models.json"
_PRESETS: Final = {
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
    def missing_compose(cls) -> EvalLaunchError:
        return cls("Docker Compose is required for Podman; set DOCKER_COMPOSE_BIN")

    @classmethod
    def excessive_concurrency(cls) -> EvalLaunchError:
        return cls("concurrency cannot exceed the number of selected task attempts")

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


@dataclass(frozen=True)
class LaunchOptions:
    tasks: tuple[str, ...]
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


def resolve_tasks(selection: Sequence[str]) -> tuple[str, ...]:
    values = selection or ("podman-arm64",)
    tasks: list[str] = []
    for value in values:
        expanded = _PRESETS.get(value, (_task_name(value),))
        for task in expanded:
            if task not in tasks:
                tasks.append(task)
    return tuple(tasks)


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
        "evals.terminal_bench.basecamp_pi:BasecampPiSingle",
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
    compose = environment.get("DOCKER_COMPOSE_BIN") or shutil.which("docker-compose")
    if not compose or not Path(compose).is_file():
        raise EvalLaunchError.missing_compose()
    environment["DOCKER_COMPOSE_BIN"] = compose
    wrapper_dir = _REPOSITORY_ROOT / "evals" / "terminal_bench" / "bin"
    environment["PATH"] = f"{wrapper_dir}{os.pathsep}{environment['PATH']}"
    return environment


def validate_options(options: LaunchOptions) -> None:
    if options.concurrency > len(options.tasks) * options.attempts:
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
    print(f"Tasks ({len(options.tasks)}):")
    for task in options.tasks:
        print(f"  - {task}")
    print(shlex.join(command))
    sys.stdout.flush()

    if options.dry_run:
        return 0
    options.jobs_dir.mkdir(parents=True, exist_ok=True)
    return subprocess.run(command, cwd=_REPOSITORY_ROOT, env=environment, check=False).returncode


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(parse_options(argv))
    except (EvalLaunchError, subprocess.CalledProcessError) as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
