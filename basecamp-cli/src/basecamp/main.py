"""Entry point for basecamp CLI."""

import importlib
import json
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
    run_companion = importlib.import_module("basecamp.companion.app").run_companion
    run_companion(snapshot_path, cwd, scratch_dir)


@basecamp.command("companion-analyze")
@click.option("--session-id", required=True, type=str)
@click.option(
    "--base-dir",
    required=False,
    default=None,
    type=click.Path(path_type=Path),
)
def companion_analyze(session_id: str, base_dir: Path | None) -> None:
    """Best-effort companion analysis writer for a session."""
    analyzer = importlib.import_module("basecamp.companion.analyzer")
    analysis = importlib.import_module("basecamp.companion.analysis")
    model = analyzer.resolve_companion_model()

    try:
        envelope = json.load(sys.stdin)
    except Exception:
        # Best-effort: any stdin read/parse failure falls back to the last-good sidecar.
        envelope = {}

    context = envelope.get("context", "") if isinstance(envelope, dict) else ""
    already_tracked = envelope.get("alreadyTracked", "") if isinstance(envelope, dict) else ""

    path = analysis.companion_analysis_path(session_id, base_dir)
    prior = analysis.load_analysis(path)

    try:
        result = analyzer.generate_analysis(
            session_id=session_id,
            model=model,
            context=context,
            already_tracked=already_tracked,
            prior=prior,
        )
        analysis.write_analysis(path, result)
    except Exception:
        click.echo("companion-analyze failed; keeping existing analysis", err=True)


@basecamp.command()
@click.option(
    "--uds",
    type=click.Path(path_type=Path),
    default=Path("~/.pi/agent/basecamp/daemon.sock").expanduser(),
    show_default=True,
    help="Unix domain socket path for the daemon listener.",
)
@click.option(
    "--db",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional SQLite database path.",
)
def daemon(uds: Path, db: Path | None) -> None:
    """Run the basecamp async-agent daemon."""
    run_daemon = importlib.import_module("basecamp.daemon.server").run_daemon
    run_daemon(str(uds), str(db) if db is not None else None)


if __name__ == "__main__":
    basecamp()
