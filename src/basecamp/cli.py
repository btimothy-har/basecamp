"""Basecamp CLI — composition layer for all sub-packages."""

from __future__ import annotations

import sys
from pathlib import Path

import rich_click as click

from basecamp.companion.app import run_companion
from basecamp.core.cli.config import run_project_menu
from basecamp.core.cli.project import (
    execute_project_add,
    execute_project_edit,
    execute_project_list,
    execute_project_remove,
)
from basecamp.core.exceptions import LauncherError
from basecamp.hub.server import run_daemon as run_swarm_daemon
from basecamp.installer import run_interactive_install
from basecamp.setup import execute_setup
from basecamp.workspace import EnvironmentConfig, remove_environment, set_environment
from basecamp.workspace.cli.environment import (
    execute_environment_list,
    run_environments_menu,
)
from basecamp.workspace.ui import console, err_console

click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def _handle_error(e: LauncherError) -> None:
    err_console.print(f"[red]Error:[/red] {e}")
    sys.exit(1)


@click.group(context_settings=CONTEXT_SETTINGS)
def basecamp() -> None:
    """basecamp - project configuration and workspace management."""


@basecamp.command()
def setup() -> None:
    """Set up basecamp environment (prerequisites, directories, config)."""
    try:
        execute_setup()
    except LauncherError as e:
        _handle_error(e)


@basecamp.group(invoke_without_command=True)
@click.pass_context
def environments(ctx: click.Context) -> None:
    """Manage per-repo worktree setup environments."""
    if ctx.invoked_subcommand is None:
        run_environments_menu()


@environments.command("list")
def environments_list() -> None:
    """List configured environments."""
    execute_environment_list()


@environments.command("set")
@click.argument("repo")
@click.argument("command")
def environments_set(repo: str, command: str) -> None:
    """Set the setup command for a repo."""
    set_environment(repo, EnvironmentConfig(setup=command))
    console.print(f"Environment set for {repo}.")


@environments.command("remove")
@click.argument("repo")
def environments_remove(repo: str) -> None:
    """Remove the environment for a repo."""
    remove_environment(repo)
    console.print(f"Environment removed for {repo}.")


@basecamp.group(invoke_without_command=True)
@click.pass_context
def projects(ctx: click.Context) -> None:
    """Manage configured projects."""
    if ctx.invoked_subcommand is None:
        run_project_menu()


@projects.command("list")
def projects_list() -> None:
    """List configured projects."""
    execute_project_list()


@projects.command("add")
def projects_add() -> None:
    """Interactively add a project."""
    execute_project_add()


@projects.command("edit")
@click.argument("name")
def projects_edit(name: str) -> None:
    """Interactively edit a project."""
    execute_project_edit(name)


@projects.command("remove")
@click.argument("name")
def projects_remove(name: str) -> None:
    """Remove a project."""
    execute_project_remove(name)


@basecamp.group()
def companion() -> None:
    """Live session companion commands."""


@companion.command()
@click.option(
    "--snapshot",
    "snapshot_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Path to the companion snapshot JSON.",
)
@click.option(
    "--cwd",
    "cwd",
    required=True,
    type=click.Path(path_type=Path),
    help="Git working directory for diffs.",
)
@click.option(
    "--scratch",
    "scratch_dir",
    required=False,
    default=None,
    type=click.Path(path_type=Path),
    help="Path to the basecamp scratch directory.",
)
def dashboard(snapshot_path: Path, cwd: Path, scratch_dir: Path | None) -> None:
    """Live session companion dashboard (runs in a tmux pane)."""
    run_companion(snapshot_path, cwd, scratch_dir)


@basecamp.group()
def swarm() -> None:
    """Async-agent swarm daemon commands."""


@swarm.command()
@click.option(
    "--uds",
    "uds_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Unix domain socket path for the daemon listener.",
)
@click.option(
    "--db",
    "db_path",
    required=False,
    default=None,
    type=click.Path(path_type=Path),
    help="Optional SQLite database path.",
)
@click.option(
    "--pidfile",
    "pidfile_path",
    required=False,
    default=None,
    type=click.Path(path_type=Path),
    help="Optional path to write the daemon PID file.",
)
def daemon(uds_path: Path, db_path: Path | None, pidfile_path: Path | None) -> None:
    """Run the async-agent daemon."""
    run_swarm_daemon(str(uds_path), str(db_path) if db_path else None, str(pidfile_path) if pidfile_path else None)


@basecamp.command()
def install() -> None:
    """Install or reconfigure basecamp components."""
    run_interactive_install()


def main() -> None:
    basecamp()


if __name__ == "__main__":
    main()
