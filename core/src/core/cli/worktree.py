"""Worktree implementation for basecamp CLI."""

from core.config import Config, resolve_project, validate_dirs
from core.git import (
    list_all_worktrees,
    list_worktrees,
    remove_all_worktrees,
    remove_worktree,
    resolve_repo_name,
)
from core.ui import display_all_worktrees, display_worktrees, err_console


def _get_project_repo_name(project: str, config: Config) -> str | None:
    """Get the repository folder name for a project.

    Args:
        project: The project name.
        config: The loaded configuration.

    Returns:
        The repository folder name, or None if not a git repo.

    Raises:
        ProjectNotFoundError: If the project doesn't exist.
    """
    proj_config = resolve_project(project, config)

    if not proj_config.dirs:
        return None

    resolved_dirs = validate_dirs(proj_config.dirs)
    return resolve_repo_name(resolved_dirs)


def list_all_project_worktrees() -> None:
    """List all worktrees across all repositories."""
    all_wts = list_all_worktrees()
    display_all_worktrees(all_wts)


def list_project_worktrees(project: str, config: Config) -> None:
    """List worktrees for a specific project."""
    repo_name = _get_project_repo_name(project, config)
    if not repo_name:
        err_console.print(f"[yellow]Project '{project}' is not a git repository[/yellow]")
        return
    wts = list_worktrees(repo_name)
    display_worktrees(repo_name, wts)


def clean_project_worktrees(
    project: str,
    config: Config,
    *,
    name: str | None = None,
    remove_all: bool = False,
    force: bool = False,
) -> None:
    """Clean worktrees for a project.

    Args:
        project: The project name.
        config: The loaded configuration.
        name: Specific worktree name to remove.
        remove_all: Remove all worktrees for the project.
        force: Force removal even with uncommitted changes.
    """
    repo_name = _get_project_repo_name(project, config)
    if not repo_name:
        err_console.print(f"[yellow]Project '{project}' is not a git repository[/yellow]")
        return

    if remove_all:
        # Remove all worktrees
        removed = remove_all_worktrees(repo_name, force=force)
        if removed:
            err_console.print(f"[green]Removed {len(removed)} worktree(s)[/green]")
            for wt_name in removed:
                err_console.print(f"  - {wt_name}")
        else:
            err_console.print(f"[yellow]No worktrees found for '{repo_name}'[/yellow]")
    elif name:
        # Remove specific worktree
        remove_worktree(repo_name, name, force=force)
        err_console.print(f"[green]Removed worktree '{name}'[/green]")
    else:
        # Interactive mode: list worktrees and let user choose
        wts = list_worktrees(repo_name)
        if not wts:
            err_console.print(f"[yellow]No worktrees found for '{repo_name}'[/yellow]")
            return

        display_worktrees(repo_name, wts)
        err_console.print("\nTo remove a worktree, run:")
        err_console.print(f"  basecamp worktree clean {project} <name>")
        err_console.print(f"  basecamp worktree clean {project} --all")
