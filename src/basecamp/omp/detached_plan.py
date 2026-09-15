"""Argument and repository planning for disposable OMP launches."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from basecamp.core.exceptions import LauncherError
from basecamp.omp.arguments import (
    OMP_OPTIONAL_VALUE_FLAGS,
    OMP_PROFILE_BOUNDARY,
    effective_cwd,
    is_unknown_long_option,
    option_consumes_next,
)

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


@dataclass(frozen=True)
class _IndexedArgument:
    value: str
    source_index: int | None


@dataclass(frozen=True)
class _ProfileBootstrap:
    arguments: tuple[_IndexedArgument, ...]
    profile: str | None
    alias_name: str | None
    error: str | None


def is_detached_requested(args: Sequence[str]) -> bool:
    """Return whether OMP's two-stage parsing leaves a launcher-owned flag."""
    bootstrap = _bootstrap_profile_args(args)
    index = 0
    while index < len(bootstrap.arguments):
        argument = bootstrap.arguments[index].value
        if argument == "--":
            return False
        if argument == "--detached":
            return True
        following = bootstrap.arguments[index + 1].value if index + 1 < len(bootstrap.arguments) else None
        index += 2 if option_consumes_next(argument, following) else 1
    return False


def parse_detached_arguments(
    cwd: Path,
    args: Sequence[str],
    *,
    home: Path | None = None,
) -> DetachedArguments:
    """Consume Basecamp tokens and reject OMP modes without a new session."""
    bootstrap = _bootstrap_profile_args(args)
    if bootstrap.error is not None:
        raise LauncherError(bootstrap.error)
    if bootstrap.alias_name is not None:
        message = "Detached mode cannot be combined with OMP's --alias management action."
        raise LauncherError(message)

    removed_indices: set[int] = set()
    detached_indices: set[int] = set()
    can_dispatch_command = True
    index = 0
    while index < len(bootstrap.arguments):
        token = bootstrap.arguments[index]
        argument = token.value
        if argument == "--":
            break
        if argument == "--detached":
            if token.source_index is not None:
                removed_indices.add(token.source_index)
                detached_indices.add(token.source_index)
            index += 1
            continue

        flag = _flag_name(argument)
        if flag in _SESSION_SOURCE_FLAGS:
            message = f"Detached mode starts a new session and cannot be combined with {flag}."
            raise LauncherError(message)
        following = bootstrap.arguments[index + 1] if index + 1 < len(bootstrap.arguments) else None
        if argument == "--cwd":
            if following is None:
                message = "Detached mode requires a value after --cwd."
                raise LauncherError(message)
            if token.source_index is not None:
                removed_indices.add(token.source_index)
            if following.source_index is not None:
                removed_indices.add(following.source_index)
            index += 2
            continue
        if argument.startswith("--cwd="):
            if token.source_index is not None:
                removed_indices.add(token.source_index)
            index += 1
            continue
        if flag == "--session-dir":
            _validate_session_dir(argument, following.value if following is not None else None)

        following_value = following.value if following is not None else None
        consumes_next = option_consumes_next(argument, following_value)
        if can_dispatch_command and not argument.startswith("-"):
            if argument in _NON_LAUNCH_COMMANDS:
                message = f"Detached mode only starts OMP sessions; remove --detached before using '{argument}'."
                raise LauncherError(message)
            can_dispatch_command = False
        index += 2 if consumes_next else 1

    source_args = tuple(
        token.value
        for token in bootstrap.arguments
        if token.source_index is None or token.source_index not in detached_indices
    )
    source_cwd = effective_cwd(cwd, source_args, home=home)
    omp_args = tuple(argument for index, argument in enumerate(args) if index not in removed_indices)
    return DetachedArguments(
        source_cwd=source_cwd,
        omp_args=omp_args,
        profile=bootstrap.profile,
    )


def _bootstrap_profile_args(args: Sequence[str]) -> _ProfileBootstrap:
    stripped: list[_IndexedArgument] = []
    profile: str | None = None
    alias_name: str | None = None
    error: str | None = None
    insert_boundary = False
    pass_through = False
    index = 0

    while index < len(args):
        argument = args[index]
        if pass_through:
            stripped.append(_IndexedArgument(argument, index))
            index += 1
            continue
        if insert_boundary:
            if not argument.startswith("-"):
                stripped.append(_IndexedArgument(OMP_PROFILE_BOUNDARY, None))
            insert_boundary = False
        if argument == "--":
            pass_through = True
            stripped.append(_IndexedArgument(argument, index))
            index += 1
            continue

        flag = _flag_name(argument)
        if flag in {"--profile", "--alias"}:
            inline = argument.startswith(f"{flag}=")
            value = argument.partition("=")[2] if inline else (args[index + 1] if index + 1 < len(args) else "")
            if not value or (not inline and value.startswith("-")):
                error = f"{flag} requires a {'profile name' if flag == '--profile' else 'command name'}."
                stripped.append(_IndexedArgument(argument, index))
                index += 1
                continue
            if flag == "--profile":
                profile = value
            else:
                alias_name = value
            insert_boundary = _needs_profile_boundary(stripped)
            index += 1 if inline else 2
            continue

        stripped.append(_IndexedArgument(argument, index))
        following = args[index + 1] if index + 1 < len(args) else None
        if argument == "--detached":
            index += 1
            continue
        if argument == "--plan":
            consumes_next = following is not None and not following.startswith("-")
        else:
            consumes_next = option_consumes_next(argument, following)
        if consumes_next and following is not None:
            stripped.append(_IndexedArgument(following, index + 1))
            index += 1
        index += 1

    return _ProfileBootstrap(
        arguments=tuple(stripped),
        profile=profile,
        alias_name=alias_name,
        error=error,
    )


def _needs_profile_boundary(arguments: Sequence[_IndexedArgument]) -> bool:
    if not arguments:
        return False
    previous = arguments[-1].value
    return previous == "--plan" or previous in OMP_OPTIONAL_VALUE_FLAGS or is_unknown_long_option(previous)


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
    if worktree_base == source.root or worktree_base.is_relative_to(source.root):
        message = f"Detached mode requires OMP's worktree base to be outside the source checkout: {worktree_base}"
        raise LauncherError(message)
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
    return config_base or _default_worktree_base(profile, environ, home, source_cwd)


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
    trimmed = value.strip() if value is not None else ""
    if not trimmed:
        return None
    if trimmed == "~":
        return home
    if trimmed.startswith(("~/", "~\\")):
        return Path(f"{home}{trimmed[1:]}").resolve()
    path = Path(trimmed)
    return path.resolve() if path.is_absolute() else None


def _default_worktree_base(
    profile: str | None,
    environ: Mapping[str, str],
    home: Path,
    source_cwd: Path,
) -> Path:
    active_profile = _active_profile(profile, environ)
    config_name = (environ.get("PI_CONFIG_DIR") or ".omp").lstrip("/\\")
    base_config_root = (home / config_name).resolve()
    config_root = base_config_root
    if active_profile is not None:
        config_root = config_root / "profiles" / active_profile

    xdg_data = environ.get("XDG_DATA_HOME")
    has_custom_agent_dir = _has_custom_agent_dir(
        active_profile,
        environ,
        source_cwd=source_cwd,
        base_config_root=base_config_root,
    )
    if sys.platform in {"darwin", "linux"} and xdg_data and not has_custom_agent_dir:
        xdg_root = Path(xdg_data) / "omp"
        if active_profile is not None:
            xdg_root = xdg_root / "profiles" / active_profile
        if xdg_root.is_absolute() and xdg_root.exists():
            return (xdg_root / "wt").resolve()
    return (config_root / "wt").resolve()


def _has_custom_agent_dir(
    active_profile: str | None,
    environ: Mapping[str, str],
    *,
    source_cwd: Path,
    base_config_root: Path,
) -> bool:
    value = environ.get("PI_CODING_AGENT_DIR")
    if active_profile is not None or not value:
        return False
    configured = Path(value)
    resolved = (source_cwd / configured).resolve() if not configured.is_absolute() else configured.resolve()
    default_agent = (base_config_root / "agent").resolve()
    if resolved == default_agent:
        return False

    bypassed_profile = _normalized_profile(environ.get("PI_PROFILE"))
    if "OMP_PROFILE" in environ and bypassed_profile is not None:
        profile_agent = (base_config_root / "profiles" / bypassed_profile / "agent").resolve()
        if resolved == profile_agent:
            return False
    return True


def _active_profile(profile: str | None, environ: Mapping[str, str]) -> str | None:
    selected = profile
    if selected is None:
        selected = environ.get("OMP_PROFILE") if "OMP_PROFILE" in environ else environ.get("PI_PROFILE")
    return _normalized_profile(selected)


def _normalized_profile(profile: str | None) -> str | None:
    normalized = profile.strip() if profile is not None else ""
    return None if not normalized or normalized == "default" else normalized


def _flag_name(argument: str) -> str:
    return argument.partition("=")[0] if argument.startswith("--") else argument


def _validate_session_dir(argument: str, following: str | None) -> None:
    value = argument.removeprefix("--session-dir=") if argument.startswith("--session-dir=") else following or ""
    if value and Path(value).is_absolute():
        return
    message = "Detached mode requires --session-dir to use an absolute path outside the disposable checkout."
    raise LauncherError(message)
