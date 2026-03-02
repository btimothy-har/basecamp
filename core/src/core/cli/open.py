"""Open implementation for basecamp CLI."""

import subprocess
from pathlib import Path

from core.config import Config, resolve_project, validate_dirs
from core.constants import SCRIPT_DIR
from core.exceptions import NoDirectoriesConfiguredError
from core.git import WorktreeInfo, attach_worktree
from core.ui import console
from core.utils import atomic_write_json


def execute_open(
    project_name: str,
    config: Config,
    *,
    new_window: bool = False,
    label: str | None = None,
) -> None:
    """Open VS Code with basecamp and project directories.

    Creates a .code-workspace file and opens it, giving a clean workspace
    with exactly the specified folders.

    Args:
        project_name: The project to open.
        config: The loaded configuration.
        new_window: Whether to open in a new VS Code window.
        label: Label of an existing worktree to open instead of primary dir.

    Raises:
        ProjectNotFoundError: If the project is not in the config.
        NoDirectoriesConfiguredError: If the project has no directories.
        DirectoryNotFoundError: If any project directories don't exist.
        NotAGitRepoError: If label provided but directory is not a git repo.
        WorktreeNotFoundError: If labeled worktree doesn't exist.
    """
    project = resolve_project(project_name, config)

    if not project.dirs:
        raise NoDirectoriesConfiguredError(project_name)

    # Validate and resolve directories
    resolved_dirs = validate_dirs(project.dirs)
    original_primary = resolved_dirs[0]

    # Handle worktree attachment for open (must exist)
    worktree_info: WorktreeInfo | None = None
    if label:
        primary_dir, worktree_info = attach_worktree(original_primary, label)
    else:
        primary_dir = original_primary

    secondary_dirs = resolved_dirs[1:]

    # Build workspace file content: primary (or worktree), secondary, then basecamp last
    folders = [{"path": str(primary_dir)}]
    folders.extend({"path": str(directory)} for directory in secondary_dirs)
    folders.append({"path": str(SCRIPT_DIR)})

    workspace_content = {"folders": folders}

    # Write workspace file to ~/.workspaces/ directory
    workspaces_dir = Path.home() / ".workspaces"

    # Include worktree name in workspace filename if attaching
    if worktree_info:
        workspace_file = workspaces_dir / f"{project_name}-{worktree_info.name}.code-workspace"
    else:
        workspace_file = workspaces_dir / f"{project_name}.code-workspace"

    atomic_write_json(workspace_file, workspace_content)

    # Display info
    console.print(f"\n[bold blue]Opening VS Code[/bold blue] for project [cyan]{project_name}[/cyan]")
    if worktree_info:
        console.print(f"  [dim]Worktree:[/dim] {worktree_info.name}")
        console.print(f"  [dim]Branch:[/dim] {worktree_info.branch}")
    console.print("  [dim]Folders:[/dim]")
    console.print(f"    • {primary_dir}")
    for directory in secondary_dirs:
        console.print(f"    • {directory}")
    console.print(f"    • {SCRIPT_DIR}")
    console.print(f"  [dim]Workspace:[/dim] {workspace_file}")
    console.print()

    vscode_flag = "--new-window" if new_window else "-r"
    subprocess.Popen(["code", vscode_flag, str(workspace_file)])
