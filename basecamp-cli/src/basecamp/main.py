"""Entry point for basecamp CLI."""

import importlib
import sys
from pathlib import Path

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


@basecamp.command()
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
def companion(snapshot_path: Path, cwd: Path) -> None:
    """Live session companion dashboard (runs in a tmux pane)."""
    run_companion = importlib.import_module("basecamp.companion.app").run_companion
    run_companion(snapshot_path, cwd)


if __name__ == "__main__":
    basecamp()
