"""Worktree management commands for basecamp."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import rich_click as click

from basecamp.config import load_projects, resolve_project, validate_dirs
from basecamp.constants import WORKTREES_DIR
from basecamp.exceptions import LauncherError
from basecamp.ui import console, err_console, format_age


def _load_worktrees(repo_name: str) -> list[dict]:
    """Return all worktree metadata for a repo, most-recent first."""
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
        data["_meta_file"] = str(meta_file)
        worktrees.append(data)
    return sorted(worktrees, key=lambda w: w.get("created_at", ""), reverse=True)


def _merged_branches(source_dir: str) -> set[str]:
    """Return branch names merged into main or master."""
    for main_branch in ("main", "master"):
        result = subprocess.run(
            ["git", "-C", source_dir, "branch", "--merged", main_branch],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return {b.strip().lstrip("* ") for b in result.stdout.splitlines() if b.strip()}
    return set()


def _delete_worktree(source_dir: str, wt: dict) -> tuple[bool, str]:
    """Remove worktree from git, delete branch, unlink meta file."""
    path = Path(wt["path"])
    branch = wt.get("branch", "")
    meta_file = Path(wt["_meta_file"])

    if path.is_dir():
        result = subprocess.run(
            ["git", "-C", source_dir, "worktree", "remove", "--force", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False, result.stderr.strip()
    else:
        subprocess.run(["git", "-C", source_dir, "worktree", "prune"], check=False, capture_output=True)

    if branch:
        subprocess.run(
            ["git", "-C", source_dir, "branch", "-D", branch],
            check=False,
            capture_output=True,
        )

    meta_file.unlink(missing_ok=True)
    return True, ""


@click.command("clean")
@click.argument("project")
def worktree_clean(project: str) -> None:
    """Interactively delete worktrees, their branches, and metadata."""
    projects = load_projects()
    try:
        proj = resolve_project(project, projects)
        primary_dir = str(validate_dirs(proj.dirs)[0])
    except LauncherError as e:
        err_console.print(f"[red]{e}[/red]")
        raise SystemExit(1) from e

    repo_name = Path(primary_dir).name
    worktrees = _load_worktrees(repo_name)

    if not worktrees:
        console.print(f"[dim]No worktrees for {repo_name}.[/dim]")
        return

    merged = _merged_branches(primary_dir)

    console.print()
    console.print(f"[dim]Worktrees for[/dim] [bold]{repo_name}[/bold][dim]:[/dim]")
    for i, wt in enumerate(worktrees, 1):
        age = format_age(wt.get("created_at", ""))
        branch = wt.get("branch", "")
        path_ok = Path(wt.get("path", "")).is_dir()

        tags = []
        if not path_ok:
            tags.append("[yellow]stale[/yellow]")
        if branch in merged:
            tags.append("[green]merged[/green]")
        tag_str = "  " + " · ".join(tags) if tags else ""

        console.print(f"  [cyan]{i}[/cyan]  {wt['name']:<24} [dim]{branch}[/dim]  [dim]{age}[/dim]{tag_str}")
    console.print()

    try:
        raw = input(f"Select to delete [1-{len(worktrees)}, space-separated, Enter to cancel]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if not raw:
        return

    selected = [
        worktrees[int(token) - 1] for token in raw.split() if token.isdigit() and 0 < int(token) <= len(worktrees)
    ]

    if not selected:
        console.print("[dim]Nothing selected.[/dim]")
        return

    names = ", ".join(w["name"] for w in selected)
    console.print(f"\nDelete [bold]{names}[/bold] (worktree + branch + metadata)")

    try:
        confirm = input("Confirm [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return

    if confirm != "y":
        console.print("[dim]Cancelled.[/dim]")
        return

    for wt in selected:
        ok, err = _delete_worktree(primary_dir, wt)
        if ok:
            console.print(f"  [green]✓[/green]  {wt['name']}")
        else:
            console.print(f"  [red]✗[/red]  {wt['name']}: {err}")
