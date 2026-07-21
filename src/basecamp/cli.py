"""Basecamp CLI — composition layer for all sub-packages."""

from __future__ import annotations

import sys
from pathlib import Path

import rich_click as click

from basecamp.companion.app import run_companion
from basecamp.config_cli.config_group import config
from basecamp.core.console import err_console
from basecamp.core.doctor import run_doctor
from basecamp.core.exceptions import LauncherError
from basecamp.hub.server import run_hub
from basecamp.installer import run_interactive_install
from basecamp.setup import execute_setup

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


@basecamp.command()
@click.option("--fix", is_flag=True, help="Apply lossless config repairs (off by default).")
@click.option("--clean", is_flag=True, help="Reclaim provably-unused runtime, prompting per item.")
@click.option("--stale-days", default=30, show_default=True, help="Idle days before runtime counts as stale.")
def doctor(*, fix: bool, clean: bool, stale_days: int) -> None:
    """Diagnose (and optionally repair) basecamp configuration and runtime."""
    raise SystemExit(run_doctor(fix=fix, clean=clean, stale_days=stale_days))


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
def tui(snapshot_path: Path, cwd: Path, scratch_dir: Path | None) -> None:
    """Live session companion TUI (runs in a side pane)."""
    run_companion(snapshot_path, cwd, scratch_dir)


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
    """Run the basecamp hub daemon."""
    run_hub(str(uds_path), str(db_path) if db_path else None, str(pidfile_path) if pidfile_path else None)


@basecamp.command()
def install() -> None:
    """Install or reconfigure basecamp components."""
    run_interactive_install()


basecamp.add_command(config)


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
