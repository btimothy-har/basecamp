"""OMP launch token inspection and Basecamp-owned argument handling."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from basecamp.core.exceptions import LauncherError
from basecamp.omp.arguments import (
    OMP_OPTIONAL_VALUE_FLAGS,
    OMP_PROFILE_BOUNDARY,
    effective_cwd,
    is_unknown_long_option,
    option_consumes_next,
)

type LaunchDisposition = Literal["auto", "direct", "discard"]

_BASECAMP_FLAGS = frozenset({"--detached", "--direct"})
_SESSION_SOURCE_FLAGS = frozenset({"--continue", "-c", "--resume", "-r", "--fork", "--session"})
_FOREIGN_IMPORT_FLAGS = frozenset({"--from-claude", "--from-codex"})
_DIRECT_FLAGS = frozenset(
    {
        "--help",
        "-h",
        "--mode",
        "--no-session",
        "--plan-yolo",
        "--plan-yolo-into",
        "--prewalk",
        "--prewalk-into",
        "--print",
        "-p",
        "--version",
        "-v",
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

_RELOCATED_PATH_FLAGS = frozenset(
    {
        "--add-dir",
        "--extension",
        "-e",
        "--hook",
        "--plugin-dir",
        "--trusted-extension",
    }
)
_FILE_OR_LITERAL_FLAGS = frozenset({"--append-system-prompt", "--system-prompt"})


@dataclass(frozen=True)
class LaunchArguments:
    """Placement and forwarded arguments for one OMP invocation."""

    disposition: LaunchDisposition
    omp_args: tuple[str, ...]
    profile: str | None


@dataclass(frozen=True)
class DetachedArguments:
    """User launch arguments after Basecamp-owned tokens are removed."""

    source_cwd: Path
    omp_args: tuple[str, ...]
    profile: str | None


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


def inspect_launch_arguments(args: Sequence[str]) -> LaunchArguments:
    """Classify one bomp invocation without changing OMP token semantics."""
    bootstrap = _bootstrap_profile_args(args)
    if bootstrap.error is not None:
        raise LauncherError(bootstrap.error)

    removed_indices: set[int] = set()
    basecamp_flags: set[str] = set()
    requires_direct = bootstrap.alias_name is not None
    can_dispatch_command = True
    index = 0
    while index < len(bootstrap.arguments):
        token = bootstrap.arguments[index]
        argument = token.value
        if argument == "--":
            break
        if argument in _BASECAMP_FLAGS:
            basecamp_flags.add(argument)
            if token.source_index is not None:
                removed_indices.add(token.source_index)
            index += 1
            continue

        following = bootstrap.arguments[index + 1] if index + 1 < len(bootstrap.arguments) else None
        following_value = following.value if following is not None else None
        flag = _flag_name(argument)
        consumes_next = _consumes_next(argument, following_value)
        if flag in _SESSION_SOURCE_FLAGS:
            requires_direct = True
        if flag in _FOREIGN_IMPORT_FLAGS or flag in _DIRECT_FLAGS:
            requires_direct = True
        if can_dispatch_command and not argument.startswith("-"):
            requires_direct = requires_direct or argument in _NON_LAUNCH_COMMANDS
            can_dispatch_command = False
        index += 2 if consumes_next else 1

    if basecamp_flags == _BASECAMP_FLAGS:
        message = "--direct and --detached cannot be combined."
        raise LauncherError(message)
    if "--detached" in basecamp_flags:
        disposition: LaunchDisposition = "discard"
    elif "--direct" in basecamp_flags or requires_direct:
        disposition = "direct"
    else:
        disposition = "auto"
    omp_args = tuple(argument for offset, argument in enumerate(args) if offset not in removed_indices)
    return LaunchArguments(
        disposition=disposition,
        omp_args=omp_args,
        profile=bootstrap.profile,
    )


def parse_detached_arguments(
    cwd: Path,
    args: Sequence[str],
    *,
    home: Path | None = None,
) -> DetachedArguments:
    """Consume Basecamp tokens and reject OMP modes without a new session."""
    inspect_launch_arguments(args)
    bootstrap = _bootstrap_profile_args(args)
    if bootstrap.alias_name is not None:
        message = "Detached mode cannot be combined with OMP's --alias management action."
        raise LauncherError(message)

    removed_indices: set[int] = set()
    basecamp_indices: set[int] = set()
    can_dispatch_command = True
    index = 0
    while index < len(bootstrap.arguments):
        token = bootstrap.arguments[index]
        argument = token.value
        if argument == "--":
            break
        if argument in _BASECAMP_FLAGS:
            if token.source_index is not None:
                removed_indices.add(token.source_index)
                basecamp_indices.add(token.source_index)
            index += 1
            continue

        following = bootstrap.arguments[index + 1] if index + 1 < len(bootstrap.arguments) else None
        following_value = following.value if following is not None else None
        flag = _flag_name(argument)
        if flag in _SESSION_SOURCE_FLAGS or flag in _FOREIGN_IMPORT_FLAGS:
            message = f"Detached mode starts a new session and cannot be combined with {flag}."
            raise LauncherError(message)
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
        consumes_next = _consumes_next(argument, following_value)
        if flag == "--session-dir":
            _validate_session_dir(argument, following_value)
        if can_dispatch_command and not argument.startswith("-"):
            if argument in _NON_LAUNCH_COMMANDS:
                message = f"Detached mode only starts OMP sessions; remove --detached before using '{argument}'."
                raise LauncherError(message)
            can_dispatch_command = False
        index += 2 if consumes_next else 1

    source_args = tuple(
        token.value
        for token in bootstrap.arguments
        if token.source_index is None or token.source_index not in basecamp_indices
    )
    source_cwd = effective_cwd(cwd, source_args, home=home)
    omp_args = tuple(argument for offset, argument in enumerate(args) if offset not in removed_indices)
    return DetachedArguments(source_cwd=source_cwd, omp_args=omp_args, profile=bootstrap.profile)


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
        if argument in _BASECAMP_FLAGS:
            index += 1
            continue
        if argument == "--plan":
            consumes_next = following is not None and not following.startswith("-")
        else:
            consumes_next = _consumes_next(argument, following)
        if consumes_next and following is not None:
            stripped.append(_IndexedArgument(following, index + 1))
            index += 1
        index += 1
    return _ProfileBootstrap(tuple(stripped), profile, alias_name, error)


def _consumes_next(argument: str, following: str | None) -> bool:
    if following in _BASECAMP_FLAGS:
        return False
    return option_consumes_next(argument, following)


def _needs_profile_boundary(arguments: Sequence[_IndexedArgument]) -> bool:
    if not arguments:
        return False
    previous = arguments[-1].value
    return previous == "--plan" or previous in OMP_OPTIONAL_VALUE_FLAGS or is_unknown_long_option(previous)


def resolve_session_dir_argument(
    args: Sequence[str],
    source_cwd: Path,
) -> tuple[tuple[str, ...], str | None]:
    """Forward ``--session-dir`` as an absolute path anchored at the source cwd.

    Managed launches change the child's real cwd, so a relative override would
    otherwise land inside the scratch; direct passthrough keeps native tokens.
    """
    tokens = list(args)
    resolved: str | None = None
    index = 0
    while index < len(tokens):
        argument = tokens[index]
        if argument == "--":
            break
        if argument == "--session-dir" or argument.startswith("--session-dir="):
            inline = argument.partition("=")[2] if "=" in argument else None
            if inline is not None:
                absolute = _absolute_session_dir(inline, source_cwd)
                if absolute is not None:
                    tokens[index] = f"--session-dir={absolute}"
                    resolved = absolute
                index += 1
                continue
            following = tokens[index + 1] if index + 1 < len(tokens) else None
            if following is None:
                index += 1
                continue
            absolute = _absolute_session_dir(following, source_cwd)
            if absolute is not None:
                tokens[index + 1] = absolute
                resolved = absolute
            index += 2
            continue
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        index += 2 if _consumes_next(argument, following) else 1
    return tuple(tokens), resolved


def resolve_relocated_path_arguments(args: Sequence[str], source_cwd: Path) -> tuple[str, ...]:
    """Anchor path-valued launch arguments before moving the child into a scratch."""
    tokens = list(args)
    index = 0
    while index < len(tokens):
        argument = tokens[index]
        if argument == "--":
            break
        flag = _flag_name(argument)
        if flag in _RELOCATED_PATH_FLAGS or flag in _FILE_OR_LITERAL_FLAGS:
            inline = argument.partition("=")[2] if argument.startswith("--") and "=" in argument else None
            value_index = index if inline is not None else index + 1
            value = inline if inline is not None else (tokens[value_index] if value_index < len(tokens) else "")
            if value and (flag in _RELOCATED_PATH_FLAGS or _source_file_exists(value, source_cwd)):
                absolute = _absolute_launch_path(value, source_cwd)
                tokens[value_index] = f"{flag}={absolute}" if inline is not None else absolute
            index += 1 if inline is not None else 2
            continue
        if argument.startswith("@") and len(argument) > 1:
            value = argument[1:]
            if len(value) > 1 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            tokens[index] = f"@{_absolute_launch_path(value, source_cwd)}"
            index += 1
            continue
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        index += 2 if _consumes_next(argument, following) else 1
    return tuple(tokens)


def _absolute_launch_path(value: str, source_cwd: Path) -> str:
    path = Path(value)
    return str((path if path.is_absolute() else source_cwd / path).resolve())


def _source_file_exists(value: str, source_cwd: Path) -> bool:
    path = Path(value)
    return (path if path.is_absolute() else source_cwd / path).is_file()


def resolve_session_dir_environment(
    environ: Mapping[str, str],
    source_cwd: Path,
) -> tuple[dict[str, str], str | None]:
    """Anchor OMP's environment-provided session directory before cwd relocation."""
    environment = dict(environ)
    value = environment.get("PI_CODING_AGENT_SESSION_DIR")
    absolute = _absolute_session_dir(value or "", source_cwd)
    if absolute is None:
        return environment, None
    environment["PI_CODING_AGENT_SESSION_DIR"] = absolute
    return environment, absolute


def _absolute_session_dir(value: str, source_cwd: Path) -> str | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = source_cwd / path
    return str(path.resolve())


def _flag_name(argument: str) -> str:
    return argument.partition("=")[0] if argument.startswith("--") else argument


def _validate_session_dir(argument: str, following: str | None) -> None:
    value = argument.removeprefix("--session-dir=") if argument.startswith("--session-dir=") else following or ""
    if value and Path(value).is_absolute():
        return
    message = "Detached mode requires --session-dir to use an absolute path outside the disposable checkout."
    raise LauncherError(message)
