"""Argument and repository planning for disposable OMP launches."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from basecamp.core.exceptions import LauncherError
from basecamp.omp.arguments import effective_cwd, option_consumes_next

_COMMAND_TIMEOUT_SECONDS = 10
_SESSION_SOURCE_FLAGS = frozenset(
    {
        "--continue",
        "--fork",
        "--from-claude",
        "--from-codex",
        "--resume",
        "--session",
        "-c",
        "-r",
    }
)
_NON_LAUNCH_COMMANDS = frozenset(
    {
        "__complete",
        "agents",
        "auth-broker",
        "auth-gateway",
        "bench",
        "browser-relay",
        "cleanse",
        "collab",
        "commit",
        "completions",
        "compress",
        "config",
        "dry-balance",
        "gallery",
        "gc",
        "git",
        "grep",
        "grievances",
        "help",
        "if-bench",
        "images",
        "img",
        "install",
        "join",
        "models",
        "plugin",
        "ps",
        "q",
        "read",
        "render",
        "say",
        "search",
        "setup",
        "share",
        "shell",
        "ssh",
        "stats",
        "tiny-models",
        "token",
        "ttsr",
        "update",
        "usage",
        "worktree",
        "wt",
    }
)


@dataclass(frozen=True)
class DetachedArguments:
    """User launch arguments after Basecamp-owned tokens are removed."""

    source_cwd: Path
    omp_args: tuple[str, ...]
    profile: str | None


@dataclass(frozen=True)
class GitSource:
    """Clean source checkout used to create a detached worktree."""

    root: Path
    relative_cwd: Path
    head: str


@dataclass(frozen=True)
class DetachedPlan:
    """Inputs required before the disposable worktree is created."""

    arguments: DetachedArguments
    source: GitSource
    worktree_base: Path


def is_detached_requested(args: Sequence[str]) -> bool:
    """Return whether an unconsumed launcher-owned flag enables detached mode."""
    index = 0
    while index < len(args):
        argument = args[index]
        if argument == "--":
            return False
        if argument == "--detached":
            return True
        following = args[index + 1] if index + 1 < len(args) else None
        index += 2 if option_consumes_next(argument, following) else 1
    return False


def parse_detached_arguments(
    cwd: Path,
    args: Sequence[str],
    *,
    home: Path | None = None,
) -> DetachedArguments:
    """Consume Basecamp tokens and reject OMP modes without a new session."""
    source_cwd = effective_cwd(cwd, args, home=home)
    omp_args: list[str] = []
    profile: str | None = None
    can_dispatch_command = True
    index = 0

    while index < len(args):
        argument = args[index]
        if argument == "--":
            omp_args.extend(args[index:])
            break
        if argument == "--detached":
            index += 1
            continue

        flag = _flag_name(argument)
        if flag in _SESSION_SOURCE_FLAGS:
            message = f"Detached mode starts a new session and cannot be combined with {flag}."
            raise LauncherError(message)
        if argument == "--cwd":
            if index + 1 >= len(args):
                message = "Detached mode requires a value after --cwd."
                raise LauncherError(message)
            index += 2
            continue
        if argument.startswith("--cwd="):
            index += 1
            continue
        if argument == "--profile":
            profile = _profile_value(args, index)
        elif argument.startswith("--profile="):
            profile = argument.removeprefix("--profile=")
            if not profile:
                message = "--profile requires a profile name."
                raise LauncherError(message)

        following = args[index + 1] if index + 1 < len(args) else None
        consumes_next = option_consumes_next(argument, following)
        if can_dispatch_command and not argument.startswith("-"):
            if argument in _NON_LAUNCH_COMMANDS:
                message = f"Detached mode only starts OMP sessions; remove --detached before using '{argument}'."
                raise LauncherError(message)
            can_dispatch_command = False
        omp_args.append(argument)
        if consumes_next and following is not None:
            omp_args.append(following)
            index += 1
        index += 1

    return DetachedArguments(
        source_cwd=source_cwd,
        omp_args=tuple(omp_args),
        profile=profile,
    )


def plan_detached_launch(
    cwd: Path,
    args: Sequence[str],
    *,
    omp_executable: str,
    environ: Mapping[str, str],
    home: Path | None = None,
) -> DetachedPlan:
    """Resolve and validate all detached-launch inputs without creating state."""
    active_home = (home or Path.home()).resolve()
    arguments = parse_detached_arguments(cwd, args, home=active_home)
    source = resolve_git_source(arguments.source_cwd)
    worktree_base = resolve_worktree_base(
        omp_executable,
        source_cwd=arguments.source_cwd,
        profile=arguments.profile,
        environ=environ,
        home=active_home,
    )
    return DetachedPlan(arguments=arguments, source=source, worktree_base=worktree_base)


def resolve_git_source(cwd: Path) -> GitSource:
    """Resolve a clean Git worktree and its selected nested directory."""
    selected = cwd.resolve()
    if not selected.is_dir():
        message = f"Detached mode requires an existing directory: {selected}"
        raise LauncherError(message)
    root_text = _run_git(selected, "rev-parse", "--show-toplevel")
    root = Path(root_text).resolve()
    try:
        relative_cwd = selected.relative_to(root)
    except ValueError as exc:
        message = f"Could not map {selected} inside its Git checkout {root}."
        raise LauncherError(message) from exc
    status = _run_git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        message = f"Detached mode requires a clean source checkout: {root}"
        raise LauncherError(message)
    head = _run_git(root, "rev-parse", "--verify", "HEAD")
    return GitSource(root=root, relative_cwd=relative_cwd, head=head)


def resolve_worktree_base(
    omp_executable: str,
    *,
    source_cwd: Path,
    profile: str | None,
    environ: Mapping[str, str],
    home: Path,
) -> Path:
    """Resolve OMP's effective managed-worktree base directory."""
    env_base = _absolute_omp_path(environ.get("OMP_WORKTREE_DIR"), home)
    if env_base is not None:
        return env_base

    command = [omp_executable]
    if profile is not None:
        command.extend(("--profile", profile))
    command.extend(("config", "get", "worktree.base", "--json"))
    try:
        result = subprocess.run(
            command,
            cwd=source_cwd,
            env=dict(environ),
            check=False,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        message = f"Could not resolve OMP worktree settings: {exc}"
        raise LauncherError(message) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        message = f"Could not resolve OMP worktree settings: {detail}"
        raise LauncherError(message)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        message = "OMP returned invalid JSON for worktree.base."
        raise LauncherError(message) from exc
    configured = payload.get("value") if isinstance(payload, dict) else None
    config_base = _absolute_omp_path(configured if isinstance(configured, str) else None, home)
    return config_base or home / ".omp" / "wt"


def _run_git(cwd: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        message = f"Could not inspect Git checkout at {cwd}: {exc}"
        raise LauncherError(message) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        message = f"Could not inspect Git checkout at {cwd}: {detail}"
        raise LauncherError(message)
    return result.stdout.strip()


def _absolute_omp_path(value: str | None, home: Path) -> Path | None:
    if not value:
        return None
    if value == "~":
        return home
    if value.startswith("~/"):
        return (home / value[2:]).resolve()
    path = Path(value)
    return path.resolve() if path.is_absolute() else None


def _flag_name(argument: str) -> str:
    return argument.partition("=")[0] if argument.startswith("--") else argument


def _profile_value(args: Sequence[str], index: int) -> str:
    if index + 1 >= len(args) or not args[index + 1] or args[index + 1].startswith("-"):
        message = "--profile requires a profile name."
        raise LauncherError(message)
    return args[index + 1]
