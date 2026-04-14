"""Shell completion functions for basecamp CLI."""

from __future__ import annotations

from click import Context, Parameter
from click.shell_completion import CompletionItem

from core.config import load_config, resolve_project, validate_dirs
from core.git import list_worktrees, resolve_repo_name


def complete_project_name(
    ctx: Context,  # noqa: ARG001
    param: Parameter,  # noqa: ARG001
    incomplete: str,
) -> list[CompletionItem]:
    """Complete project names from config."""
    try:
        config = load_config()
        return [CompletionItem(name) for name in sorted(config.projects.keys()) if name.startswith(incomplete)]
    except Exception:  # noqa: BLE001
        return []


def complete_worktree_name(
    ctx: Context,
    param: Parameter,  # noqa: ARG001
    incomplete: str,
) -> list[CompletionItem]:
    """Complete worktree names for a given project."""
    project_name = ctx.params.get("project")
    if not project_name:
        return []

    try:
        config = load_config()
        project = resolve_project(project_name, config)
        if not project.dirs:
            return []
        resolved = validate_dirs(project.dirs)
        repo_name = resolve_repo_name(resolved)
        if not repo_name:
            return []
        return [CompletionItem(wt.name) for wt in list_worktrees(repo_name) if wt.name.startswith(incomplete)]
    except Exception:  # noqa: BLE001
        return []
