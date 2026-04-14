"""Entry point for basecamp CLI."""

import sys

import rich_click as click

from core.cli.project import (
    execute_project_add,
    execute_project_edit,
    execute_project_list,
    execute_project_remove,
)
from core.cli.setup import execute_setup
from core.exceptions import LauncherError
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
    """basecamp - project configuration and workspace management."""


@basecamp.command()
def setup() -> None:
    """Set up basecamp environment (prerequisites, directories, config)."""
    try:
        execute_setup()
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
@click.argument("name")
def project_edit(name: str) -> None:
    """Interactively edit an existing project."""
    try:
        execute_project_edit(name)
    except LauncherError as e:
        _handle_error(e)


@project.command("remove")
@click.argument("name")
def project_remove(name: str) -> None:
    """Remove a project."""
    try:
        execute_project_remove(name)
    except LauncherError as e:
        _handle_error(e)


if __name__ == "__main__":
    basecamp()
