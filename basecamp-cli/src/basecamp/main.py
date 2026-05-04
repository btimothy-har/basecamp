"""Entry point for basecamp CLI."""

import sys

import rich_click as click

from basecamp.cli.config import run_config_menu
from basecamp.cli.setup import execute_setup
from basecamp.exceptions import LauncherError
from basecamp.ui import err_console

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


# --- config command ---


@basecamp.command()
def config() -> None:
    """Interactive configuration menu."""
    run_config_menu()


if __name__ == "__main__":
    basecamp()
