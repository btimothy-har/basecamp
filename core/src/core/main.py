"""Entry point for basecamp CLI."""

import sys

import rich_click as click

from core.cli.completions import complete_project_name, complete_project_or_path, complete_worktree_name
from core.cli.dispatch import execute_dispatch
from core.cli.launch import execute_launch, is_path_argument, resolve_path_argument
from core.cli.log import execute_log
from core.cli.open import execute_open
from core.cli.project import (
    execute_project_add,
    execute_project_edit,
    execute_project_list,
    execute_project_remove,
)
from core.cli.reflect import execute_reflect
from core.cli.setup import execute_setup
from core.cli.worktree import (
    clean_project_worktrees,
    list_all_project_worktrees,
    list_project_worktrees,
)
from core.config import Config, load_config
from core.exceptions import LauncherError, PathLaunchLabelError
from core.ui import err_console

# Configure rich-click
click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True

# Enable -h as alias for --help
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def _handle_error(e: LauncherError) -> None:
    """Print error and exit."""
    err_console.print(f"[red]Error:[/red] {e}")
    sys.exit(1)


@click.group(context_settings=CONTEXT_SETTINGS)
def basecamp() -> None:
    """basecamp - Claude Code multi-project workspace launcher."""


@basecamp.command()
def setup() -> None:
    """Set up basecamp environment (prerequisites, directories, config)."""
    try:
        execute_setup()
    except LauncherError as e:
        _handle_error(e)


@basecamp.command()
@click.argument("project", shell_complete=complete_project_or_path)
@click.option("--resume", "-r", "resume_session", is_flag=True, help="Resume a previous conversation")
@click.option("--label", "-l", help="Work in a labeled worktree (creates if new, re-enters if exists)")
def start(project: str, resume_session: bool, label: str | None) -> None:  # noqa: FBT001
    """Start Claude Code with a project name or directory path.

    PROJECT can be a configured project name or a filesystem path (., ./, ~/, /).
    Use -l/--label to work in an isolated git worktree (project names only).
    """
    try:
        if is_path_argument(project):
            if label:
                raise PathLaunchLabelError
            resolved = resolve_path_argument(project)
            execute_launch(resolved.name, Config(projects={}), resume=resume_session, resolved_path=resolved)
        else:
            config = load_config()
            execute_launch(project, config, resume=resume_session, label=label)
    except LauncherError as e:
        _handle_error(e)


@basecamp.command()
@click.option("--name", "-n", default=None, help="Task name (auto-generated if omitted)")
@click.option("--model", "-m", default="sonnet", help="Model for the worker session (default: sonnet)")
def dispatch(name: str | None, model: str) -> None:
    """Dispatch a worker session in a new tmux pane.

    Must be run from within a Claude session (tmux + CLAUDE_SESSION_ID).
    If --name is provided and a prompt.md exists in the task directory,
    the worker receives it as the initial message. Otherwise starts bare.
    """
    try:
        execute_dispatch(name=name, model=model)
    except LauncherError as e:
        _handle_error(e)


@basecamp.command("open")
@click.argument("project", shell_complete=complete_project_name)
@click.option("--new", "-n", "new_window", is_flag=True, help="Open in a new window")
@click.option("--label", "-l", help="Open an existing worktree by label")
def open_cmd(project: str, new_window: bool, label: str | None) -> None:  # noqa: FBT001
    """Open VS Code with basecamp and project directories.

    Use -l/--label to open an existing worktree instead of the primary directory.
    """
    try:
        config = load_config()
        execute_open(project, config, new_window=new_window, label=label)
    except LauncherError as e:
        _handle_error(e)


@basecamp.command()
@click.argument("message")
@click.option("--project", "-p", help="Add a [[Project]] page reference to the entry")
def log(message: str, project: str | None) -> None:
    """Append a block to today's Logseq daily journal."""
    try:
        execute_log(message, project=project)
    except LauncherError as e:
        _handle_error(e)


@basecamp.command()
def reflect() -> None:
    """Launch a reflective journaling session with Claude."""
    try:
        execute_reflect()
    except LauncherError as e:
        _handle_error(e)


@basecamp.group()
def project() -> None:
    """Manage basecamp projects."""


@project.command("list")
def project_list() -> None:
    """List all available projects."""
    try:
        execute_project_list()
    except LauncherError as e:
        _handle_error(e)


@project.command("add")
def project_add() -> None:
    """Interactively add a new project."""
    try:
        execute_project_add()
    except LauncherError as e:
        _handle_error(e)


@project.command("edit")
@click.argument("name", shell_complete=complete_project_name)
def project_edit(name: str) -> None:
    """Interactively edit an existing project."""
    try:
        execute_project_edit(name)
    except LauncherError as e:
        _handle_error(e)


@project.command("remove")
@click.argument("name", shell_complete=complete_project_name)
def project_remove(name: str) -> None:
    """Remove a project."""
    try:
        execute_project_remove(name)
    except LauncherError as e:
        _handle_error(e)


@basecamp.group()
def worktree() -> None:
    """Manage git worktrees for basecamp projects."""


@worktree.command("list")
@click.argument("project", required=False, shell_complete=complete_project_name)
@click.option("--all", "-a", "list_all", is_flag=True, help="List all worktrees across all repositories")
def worktree_list(project: str | None, list_all: bool) -> None:  # noqa: FBT001
    """List worktrees for a project, or all worktrees with --all."""
    if list_all and project:
        err_console.print("[red]Error:[/red] Cannot specify both --all and a project name")
        sys.exit(1)

    if not list_all and not project:
        err_console.print("[red]Error:[/red] Please specify a project or use --all to list all worktrees")
        sys.exit(1)

    try:
        if list_all:
            list_all_project_worktrees()
        else:
            config = load_config()
            list_project_worktrees(project, config)  # type: ignore[arg-type]
    except LauncherError as e:
        _handle_error(e)


@worktree.command("clean")
@click.argument("project", shell_complete=complete_project_name)
@click.argument("name", required=False, shell_complete=complete_worktree_name)
@click.option("--all", "remove_all", is_flag=True, help="Remove all worktrees for the project")
@click.option("--force", "-f", is_flag=True, help="Force removal even with uncommitted changes")
def worktree_clean(project: str, name: str | None, remove_all: bool, force: bool) -> None:  # noqa: FBT001
    """Remove worktrees for a project.

    With no arguments, shows interactive selection. Use --all to remove all worktrees,
    or specify a NAME to remove a specific worktree.
    """
    if remove_all and name:
        err_console.print("[red]Error:[/red] Cannot specify both --all and a worktree name")
        sys.exit(1)

    try:
        config = load_config()
        clean_project_worktrees(project, config, name=name, remove_all=remove_all, force=force)
    except LauncherError as e:
        _handle_error(e)


if __name__ == "__main__":
    basecamp()
