"""Launch pi with a basecamp project configuration.

Thin launcher — resolves the project directory, changes to it, and execs
pi with --project. The extension handles prompt assembly, env vars, and
all other session setup via its session_start hook.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from basecamp.config import ProjectConfig, resolve_project, validate_dirs
from basecamp.constants import WORKTREES_DIR
from basecamp.exceptions import NoDirectoriesConfiguredError

PI_COMMAND = "pi"
_console = Console()


def _list_worktrees(repo_name: str) -> list[dict]:
    """Return existing worktrees for a repo, filtered to those with valid paths."""
    meta_dir = WORKTREES_DIR / repo_name / ".meta"
    if not meta_dir.is_dir():
        return []

    worktrees = []
    for meta_file in sorted(meta_dir.glob("*.json")):
        with meta_file.open() as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                continue
        if "path" in data and Path(data["path"]).is_dir():
            worktrees.append(data)
    return worktrees


def _format_age(created_at: str) -> str:
    """Return a human-readable age string from an ISO timestamp."""
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return ""
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    days = (datetime.now(tz=timezone.utc) - created).days
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days}d ago"


def _prompt_worktree(repo_name: str) -> str | None:
    """Prompt the user to select or create a worktree, or skip.

    Returns a label string to use, or None to skip (launch on main).
    """
    worktrees = _list_worktrees(repo_name)

    if worktrees:
        _console.print()
        _console.print(f"[dim]Worktrees for[/dim] [bold]{repo_name}[/bold][dim]:[/dim]")
        for i, wt in enumerate(worktrees, 1):
            age = _format_age(wt.get("created_at", ""))
            _console.print(f"  [cyan]{i}[/cyan]  {wt['name']:<24} [dim]{wt.get('branch', '')}[/dim]  [dim]{age}[/dim]")
        _console.print()

    try:
        raw = input("Label [number/name/Enter to skip]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if not raw:
        return None

    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(worktrees):
            return worktrees[idx]["name"]
        _console.print(f"[yellow]No worktree #{raw} — using as label name.[/yellow]")

    return raw


def execute_launch(
    project_name: str | None,
    projects: dict[str, ProjectConfig] | None,
    *,
    label: str | None = None,
    style: str | None = None,
    extra_args: list[str] | None = None,
) -> None:
    """Launch a pi session for the given project.

    If project_name is None, launches pi in the current directory without
    a project. Otherwise resolves the project's primary directory, chdir's
    into it, and execs pi with the appropriate flags.

    Does not return — replaces the current process.
    """
    cmd: list[str] = [PI_COMMAND]

    if project_name is not None:
        assert projects is not None
        project = resolve_project(project_name, projects)
        if not project.dirs:
            raise NoDirectoriesConfiguredError(project_name)

        primary_dir = validate_dirs(project.dirs)[0]
        cmd.extend(["--project", project_name])
        os.chdir(primary_dir)

        if label is None:
            repo_name = Path(primary_dir).name
            label = _prompt_worktree(repo_name)

    if label:
        cmd.extend(["--label", label])
    if style:
        cmd.extend(["--style", style])
    if extra_args:
        cmd.extend(extra_args)

    os.execvp(cmd[0], cmd)
