"""Basecamp CLI — composition layer for all sub-packages."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import rich_click as click
from basecamp_core.exceptions import LauncherError
from basecamp_workspace import EnvironmentConfig, remove_environment, set_environment
from basecamp_workspace.cli.config import run_project_menu
from basecamp_workspace.cli.environment import (
    execute_environment_list,
    run_environments_menu,
)
from basecamp_workspace.cli.project import (
    execute_project_add,
    execute_project_edit,
    execute_project_list,
    execute_project_remove,
)
from basecamp_workspace.ui import console, err_console

from basecamp.installer import run_interactive_install
from basecamp.setup import execute_setup

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

try:
    from pi_swarm.server import run_daemon as run_swarm_daemon

    HAS_SWARM = True
except ImportError:
    run_swarm_daemon = None
    HAS_SWARM = False

click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

_COMPANION_NOT_INSTALLED = "companion is not installed. Run: basecamp install"
_SWARM_NOT_INSTALLED = "swarm is not installed. Run: basecamp install"


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


@basecamp.group(hidden=not HAS_COMPANION)
def companion() -> None:
    """Live session companion commands."""


@companion.command(hidden=not HAS_COMPANION)
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
    if not HAS_COMPANION:
        click.echo(_COMPANION_NOT_INSTALLED, err=True)
        raise SystemExit(1)
    run_companion(snapshot_path, cwd, scratch_dir)


@companion.command(hidden=not HAS_COMPANION)
@click.option("--session-id", required=True, type=str)
@click.option(
    "--base-dir",
    required=False,
    default=None,
    type=click.Path(path_type=Path),
)
def analyze(session_id: str, base_dir: Path | None) -> None:
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
        click.echo("companion analyze failed; keeping existing analysis", err=True)


@basecamp.command("companion-analyze", hidden=not HAS_COMPANION)
@click.option("--session-id", required=True, type=str)
@click.option(
    "--base-dir",
    required=False,
    default=None,
    type=click.Path(path_type=Path),
)
@click.pass_context
def companion_analyze(ctx: click.Context, session_id: str, base_dir: Path | None) -> None:
    """Deprecated compatibility alias for `basecamp companion analyze`."""
    if not HAS_COMPANION:
        click.echo(_COMPANION_NOT_INSTALLED, err=True)
        raise SystemExit(1)

    click.echo(
        "Warning: `basecamp companion-analyze` is deprecated; use `basecamp companion analyze`.",
        err=True,
    )
    ctx.invoke(analyze, session_id=session_id, base_dir=base_dir)


@basecamp.group(hidden=not HAS_SWARM)
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
    if not HAS_SWARM or run_swarm_daemon is None:
        click.echo(_SWARM_NOT_INSTALLED, err=True)
        raise SystemExit(1)

    run_swarm_daemon(str(uds_path), str(db_path) if db_path else None, str(pidfile_path) if pidfile_path else None)


@basecamp.command()
def install() -> None:
    """Install or reconfigure basecamp components."""
    run_interactive_install()


def main() -> None:
    basecamp()


if __name__ == "__main__":
    main()
