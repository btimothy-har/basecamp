"""Basecamp CLI — composition layer for all sub-packages."""

from __future__ import annotations

import sys
from pathlib import Path

import rich_click as click

from basecamp.claude.launch import run_launch
from basecamp.core.cli.config_group import config
from basecamp.core.cli.workstream_group import workstream
from basecamp.core.exceptions import LauncherError
from basecamp.install import execute_install
from basecamp.workspace.ui import err_console

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
def install() -> None:
    """Wire basecamp into this machine: register the plugin, install the doctrine, seed config."""
    try:
        execute_install()
    except LauncherError as e:
        _handle_error(e)


@basecamp.group()
def claude() -> None:
    """Claude Code session commands."""


@claude.command(
    "launch",
    context_settings={"ignore_unknown_options": True},
    add_help_option=False,
)
@click.argument("extra", nargs=-1, type=click.UNPROCESSED)
def claude_launch(extra: tuple[str, ...]) -> None:
    """Launch an interactive Claude session with the basecamp system prompt.

    Extra arguments pass straight through to ``claude`` (this is the same entry
    point as the ``bcc`` command).
    """
    run_launch(list(extra))


@basecamp.command()
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
def hub(uds_path: Path, db_path: Path | None, pidfile_path: Path | None) -> None:
    """Run the basecamp Claude session hub daemon."""
    db = str(db_path) if db_path else None
    pidfile = str(pidfile_path) if pidfile_path else None
    # Lazy import keeps CLI startup light.
    from basecamp.hub.claude.server import run_claude_hub  # noqa: PLC0415

    run_claude_hub(str(uds_path), db, pidfile)


basecamp.add_command(config)
basecamp.add_command(workstream)


def main() -> None:
    # Safety net: any LauncherError that reaches the top (e.g. a malformed
    # config record surfaced by a porcelain command) prints cleanly instead of
    # a traceback. Command-local handlers still catch it first where present.
    try:
        basecamp()
    except LauncherError as e:
        _handle_error(e)


if __name__ == "__main__":
    main()
