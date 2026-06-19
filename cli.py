"""Basecamp CLI — composition layer for all sub-packages."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import rich_click as click
from basecamp_cli.cli.config import run_config_menu
from basecamp_cli.cli.setup import execute_setup
from basecamp_cli.exceptions import LauncherError
from basecamp_cli.installer import run_interactive_install
from basecamp_cli.ui import err_console

# Companion is an optional component — lazy import
try:
    from companion_tui.analysis import (
        companion_analysis_path,
        load_analysis,
        write_analysis,
    )
    from companion_tui.analyzer import generate_analysis, resolve_companion_model
    from companion_tui.app import run_companion

    HAS_COMPANION = True
except ImportError:
    HAS_COMPANION = False

click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

_COMPANION_NOT_INSTALLED = "companion is not installed. Run: basecamp install"


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
def config() -> None:
    """Interactive configuration menu."""
    run_config_menu()


@basecamp.command(hidden=not HAS_COMPANION)
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
def companion(snapshot_path: Path, cwd: Path, scratch_dir: Path | None) -> None:
    """Live session companion dashboard (runs in a tmux pane)."""
    if not HAS_COMPANION:
        click.echo(_COMPANION_NOT_INSTALLED, err=True)
        raise SystemExit(1)
    run_companion(snapshot_path, cwd, scratch_dir)


@basecamp.command("companion-analyze", hidden=not HAS_COMPANION)
@click.option("--session-id", required=True, type=str)
@click.option(
    "--base-dir",
    required=False,
    default=None,
    type=click.Path(path_type=Path),
)
def companion_analyze(session_id: str, base_dir: Path | None) -> None:
    """Best-effort companion analysis writer for a session."""
    if not HAS_COMPANION:
        click.echo(_COMPANION_NOT_INSTALLED, err=True)
        raise SystemExit(1)

    model = resolve_companion_model()

    try:
        envelope = json.load(sys.stdin)
    except Exception:
        envelope = {}

    context = envelope.get("context", "") if isinstance(envelope, dict) else ""
    already_tracked = envelope.get("alreadyTracked", "") if isinstance(envelope, dict) else ""

    path = companion_analysis_path(session_id, base_dir)
    prior = load_analysis(path)

    try:
        result = generate_analysis(
            session_id=session_id,
            model=model,
            context=context,
            already_tracked=already_tracked,
            prior=prior,
        )
        write_analysis(path, result)
    except Exception:
        click.echo("companion-analyze failed; keeping existing analysis", err=True)


@basecamp.command()
def install() -> None:
    """Install or reconfigure basecamp components."""
    run_interactive_install()


def main() -> None:
    basecamp()


if __name__ == "__main__":
    main()
