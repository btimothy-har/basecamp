"""Launch pi with a basecamp project configuration.

Thin launcher — resolves the project directory, changes to it, and execs
pi with --project. The extension handles prompt assembly, env vars, and
all other session setup via its session_start hook.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from rich.console import Console

from basecamp.config import ProjectConfig, resolve_project, validate_dirs
from basecamp.constants import WORKTREES_DIR
from basecamp.exceptions import NoDirectoriesConfiguredError
from basecamp.ui import format_age

PI_COMMAND = "pi"
_console = Console()


def _list_worktrees(repo_name: str) -> list[dict]:
    """Return existing worktrees for a repo, filtered to those with valid paths."""
    meta_dir = WORKTREES_DIR / repo_name / ".meta"
    if not meta_dir.is_dir():
        return []

    worktrees = []
    for meta_file in meta_dir.glob("*.json"):
        with meta_file.open() as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                continue
        if "path" in data and Path(data["path"]).is_dir():
            worktrees.append(data)
    return sorted(worktrees, key=lambda w: w.get("created_at", ""), reverse=True)


def _prompt_worktree(repo_name: str) -> str | None:
    """Prompt the user to select or create a worktree, or skip.

    Number selects existing, any other text creates new, Enter skips.
    Returns a label string, or None to skip (launch on main).
    """
    worktrees = _list_worktrees(repo_name)

    _console.print()
    if worktrees:
        _console.print(f"[dim]Worktrees for[/dim] [bold]{repo_name}[/bold][dim]:[/dim]")
        for i, wt in enumerate(worktrees, 1):
            age = format_age(wt.get("created_at", ""))
            branch = wt.get("branch", "")
            _console.print(f"  [cyan]{i}[/cyan]  {wt['name']:<24} [dim]{branch}[/dim]  [dim]{age}[/dim]")
        _console.print()
        prompt = f"[1-{len(worktrees)} to resume, name to create, Enter to skip]: "
    else:
        prompt = "Worktree name (Enter to skip): "

    try:
        raw = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if not raw:
        return None
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(worktrees):
            return worktrees[idx]["name"]
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
