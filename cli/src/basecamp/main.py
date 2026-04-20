"""Entry point for basecamp CLI."""

import sys

import rich_click as click

from basecamp.cli.config import run_config_menu
from basecamp.cli.launch import execute_launch
from basecamp.cli.setup import execute_setup
from basecamp.config import load_projects
from basecamp.exceptions import BlockedArgError, LauncherError
from basecamp.ui import err_console

# Configure rich-click
click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True

# Enable -h as alias for --help
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

# Args that basecamp controls — block from passthrough to pi.
_BLOCKED_ARGS = {"--system-prompt", "--append-system-prompt", "--project", "--label", "--style", "--agent-prompt"}


def _handle_error(e: LauncherError) -> None:
    """Print error and exit."""
    err_console.print(f"[red]Error:[/red] {e}")
    sys.exit(1)


@click.group(context_settings=CONTEXT_SETTINGS)
def basecamp() -> None:
    """basecamp - project configuration and workspace management."""


@basecamp.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("project", required=False, default=None)
@click.option("--label", "-l", help="Work in a labeled git worktree (creates if new)")
@click.option("--style", "-s", help="Override working style")
@click.pass_context
def pi(ctx: click.Context, project: str | None, label: str | None, style: str | None) -> None:
    """Launch pi with a basecamp project.

    Run without a project name (or with ".") to launch in the current directory.
    Additional args are passed through to the pi CLI (e.g. --model, --resume).
    """
    try:
        for arg in ctx.args:
            for blocked in _BLOCKED_ARGS:
                if arg == blocked or arg.startswith(blocked + "="):
                    raise BlockedArgError(blocked)

        if project is None or project == ".":
            execute_launch(None, None, label=label, style=style, extra_args=ctx.args)
        else:
            projects = load_projects()
            execute_launch(project, projects, label=label, style=style, extra_args=ctx.args)
    except LauncherError as e:
        _handle_error(e)


@basecamp.command()
def setup() -> None:
    """Set up basecamp environment (prerequisites, directories, config)."""
    try:
        execute_setup()
    except LauncherError as e:
        _handle_error(e)


# --- config command ---


@basecamp.command()
def config() -> None:
    """Interactive configuration menu."""
    run_config_menu()


# --- bpi shorthand ---


_bpi_ctx = {"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": ["-h", "--help"]}


@click.command(context_settings=_bpi_ctx)
@click.argument("project", required=False, default=None)
@click.option("--label", "-l", help="Work in a labeled git worktree (creates if new)")
@click.option("--style", "-s", help="Override working style")
@click.pass_context
def bpi(ctx: click.Context, project: str | None, label: str | None, style: str | None) -> None:
    """Launch pi with a basecamp project (shorthand for `basecamp pi`).

    Run without a project name (or with ".") to launch in the current directory.
    Additional args are passed through to the pi CLI (e.g. --model, --resume).
    """
    try:
        for arg in ctx.args:
            for blocked in _BLOCKED_ARGS:
                if arg == blocked or arg.startswith(blocked + "="):
                    raise BlockedArgError(blocked)

        if project is None or project == ".":
            execute_launch(None, None, label=label, style=style, extra_args=ctx.args)
        else:
            projects = load_projects()
            execute_launch(project, projects, label=label, style=style, extra_args=ctx.args)
    except LauncherError as e:
        _handle_error(e)


if __name__ == "__main__":
    basecamp()
