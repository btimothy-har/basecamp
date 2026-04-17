"""Entry point for basecamp CLI."""

import sys

import rich_click as click

from core.cli.launch import execute_launch
from core.cli.model import (
    execute_model_list,
    execute_model_remove,
    execute_model_set,
)
from core.cli.project import (
    execute_project_add,
    execute_project_edit,
    execute_project_list,
    execute_project_remove,
)
from core.cli.setup import execute_setup
from core.config import load_config
from core.exceptions import BlockedArgError, LauncherError
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


# Args that basecamp controls — block from passthrough to pi.
_BLOCKED_ARGS = {"--system-prompt", "--append-system-prompt", "--project", "--label", "--style", "--agent-prompt"}


@basecamp.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("project")
@click.option("--label", "-l", help="Work in a labeled git worktree (creates if new)")
@click.option("--style", "-s", help="Override working style")
@click.pass_context
def pi(ctx: click.Context, project: str, label: str | None, style: str | None) -> None:
    """Launch pi with a basecamp project.

    Additional args are passed through to the pi CLI (e.g. --model, --resume).
    """
    try:
        for arg in ctx.args:
            for blocked in _BLOCKED_ARGS:
                if arg == blocked or arg.startswith(blocked + "="):
                    raise BlockedArgError(blocked)

        config = load_config()
        execute_launch(project, config, label=label, style=style, extra_args=ctx.args)
    except LauncherError as e:
        _handle_error(e)


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


@basecamp.group()
def model() -> None:
    """Manage model aliases."""


@model.command("list")
def model_list() -> None:
    """List all configured model aliases."""
    try:
        execute_model_list()
    except LauncherError as e:
        _handle_error(e)


@model.command("set")
@click.argument("alias")
@click.argument("model_id")
def model_set(alias: str, model_id: str) -> None:
    """Set a model alias (e.g. basecamp model set fast claude-haiku-4-5)."""
    try:
        execute_model_set(alias, model_id)
    except LauncherError as e:
        _handle_error(e)


@model.command("remove")
@click.argument("alias")
def model_remove(alias: str) -> None:
    """Remove a model alias."""
    try:
        execute_model_remove(alias)
    except LauncherError as e:
        _handle_error(e)


if __name__ == "__main__":
    basecamp()
