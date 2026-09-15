"""OMP launch argument inspection shared by Basecamp launch modes."""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from pathlib import Path

# Pinned OMP 18.1.21 launch flags. Built-in string flags consume a following
# token even when it looks like another flag.
OMP_STRING_VALUE_FLAGS = frozenset(
    {
        "--add-dir",
        "--alias",
        "--append-system-prompt",
        "--api-key",
        "--approval-mode",
        "--config",
        "--cwd",
        "--export",
        "--extension",
        "--fork",
        "--hook",
        "--max-time",
        "--mode",
        "--model",
        "--models",
        "--plan",
        "--plan-yolo-into",
        "--plugin-dir",
        "--prewalk-into",
        "--profile",
        "--prompt-cache-key",
        "--provider",
        "--provider-session-id",
        "--service-tier",
        "--session-dir",
        "--skills",
        "--slow",
        "--smol",
        "--system-prompt",
        "--thinking",
        "--tools",
        "--trusted-extension",
        "-e",
    }
)
OMP_OPTIONAL_VALUE_FLAGS = frozenset({"--resume", "--session", "-r"})
OMP_PROFILE_BOUNDARY = "--omp-profile-boundary"
OMP_VALUELESS_FLAGS = frozenset(
    {
        "--advisor",
        "--allow-home",
        "--auto-approve",
        "--continue",
        "--external-thinking",
        "--from-claude",
        "--from-codex",
        "--help",
        "--hide-thinking",
        "--no-extensions",
        "--no-lsp",
        "--no-prewalk",
        "--no-pty",
        "--no-rules",
        "--no-session",
        "--no-skills",
        "--no-title",
        "--no-tools",
        OMP_PROFILE_BOUNDARY,
        "--plan-yolo",
        "--prewalk",
        "--print",
        "--print-thoughts",
        "--version",
        "--yolo",
    }
)


def option_consumes_next(argument: str, following: str | None) -> bool:
    """Mirror OMP's pre-extension value-consumption contract."""
    if following is None or (argument.startswith("--") and "=" in argument):
        return False
    if argument in OMP_STRING_VALUE_FLAGS:
        return True
    if argument in OMP_OPTIONAL_VALUE_FLAGS:
        return bool(following) and not following.startswith("-")
    if is_unknown_long_option(argument):
        return not following.startswith("-")
    return False


def effective_cwd(
    cwd: Path,
    args: Sequence[str],
    *,
    home: Path | None = None,
) -> Path:
    """Resolve the directory OMP will use without consuming its arguments."""
    selected = cwd
    has_explicit_cwd = False
    allows_home = False
    index = 0
    while index < len(args):
        argument = args[index]
        if argument == "--":
            break
        if argument == "--cwd" and index + 1 < len(args):
            value = args[index + 1]
            selected = _resolve_cli_path(value, cwd)
            has_explicit_cwd = bool(value)
            index += 2
            continue
        if argument.startswith("--cwd="):
            value = argument.removeprefix("--cwd=")
            selected = _resolve_cli_path(value, cwd)
            has_explicit_cwd = bool(value)
            index += 1
            continue
        if argument == "--allow-home" or argument.startswith("--allow-home="):
            allows_home = True
            index += 1
            continue
        following = args[index + 1] if index + 1 < len(args) else None
        index += 2 if option_consumes_next(argument, following) else 1
    return _apply_omp_home_fallback(
        selected.resolve(),
        home=(home or Path.home()).resolve(),
        has_explicit_cwd=has_explicit_cwd,
        allows_home=allows_home,
    )


def is_unknown_long_option(argument: str) -> bool:
    return (
        argument.startswith("--")
        and "=" not in argument
        and argument not in OMP_STRING_VALUE_FLAGS
        and argument not in OMP_OPTIONAL_VALUE_FLAGS
        and argument not in OMP_VALUELESS_FLAGS
    )


def _resolve_cli_path(value: str, cwd: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else cwd / path


def _apply_omp_home_fallback(
    selected: Path,
    *,
    home: Path,
    has_explicit_cwd: bool,
    allows_home: bool,
) -> Path:
    if has_explicit_cwd or allows_home or selected != home:
        return selected
    for candidate in (home / "tmp", Path("/tmp"), Path("/var/tmp"), Path(tempfile.gettempdir())):
        try:
            if candidate.is_dir() and candidate.resolve() != selected:
                return candidate.resolve()
        except OSError:
            continue
    return selected
