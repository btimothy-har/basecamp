"""CLI entry point for the observer daemon."""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from importlib.resources import files
from urllib.parse import urlparse, urlunparse

import click
import questionary
from sqlalchemy import create_engine, text

from observer import constants
from observer.daemon import Daemon
from observer.exceptions import RegistrationError
from observer.services.config import (
    CONFIG_FILE,
    get_db_source,
    get_extraction_model,
    get_mode,
    get_pg_url,
    get_summary_model,
    set_db_source,
    set_extraction_model,
    set_mode,
    set_pg_url,
    set_summary_model,
)
from observer.services.container import (
    ContainerRuntimeNotFoundError,
    container_logs,
    detect_runtime,
    ensure_running,
    inspect_container,
    remove_container,
    remove_volume,
    stop_container,
    volume_exists,
)


@click.group()
def main() -> None:
    """Observer daemon — monitors Claude Code transcripts."""


@main.group()
def db() -> None:
    """Manage the local PostgreSQL container."""


@db.command()
def up() -> None:
    """Start the local PostgreSQL container (must be configured via setup first)."""
    source = get_db_source()
    if source is None:
        sys.exit("Database not configured. Run 'observer setup' first.")
    if source == "user":
        sys.exit("Database is externally managed. Use your own tools to start it.")

    try:
        runtime = detect_runtime()
    except ContainerRuntimeNotFoundError:
        sys.exit("Neither 'docker' nor 'podman' found on PATH.")

    _ensure_container_ready(runtime)


@db.command()
def down() -> None:
    """Stop and remove the local PostgreSQL container (data volume preserved)."""
    source = get_db_source()
    if source is None:
        sys.exit("Database not configured. Run 'observer setup' first.")
    if source == "user":
        sys.exit("Database is externally managed. Use your own tools to stop it.")

    try:
        runtime = detect_runtime()
    except ContainerRuntimeNotFoundError:
        sys.exit("Neither 'docker' nor 'podman' found on PATH.")

    status = inspect_container(runtime)

    if status is None:
        click.echo(f"Container '{constants.DB_CONTAINER_NAME}' not found.")
        return

    try:
        if status.running:
            click.echo(f"Stopping container '{constants.DB_CONTAINER_NAME}'...")
            stop_container(runtime)

        click.echo(f"Removing container '{constants.DB_CONTAINER_NAME}'...")
        remove_container(runtime)
    except RuntimeError as exc:
        sys.exit(str(exc))
    click.echo(f"Removed. Volume '{constants.DB_VOLUME_NAME}' preserved.")


@db.command()
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
def reset(yes: bool) -> None:  # noqa: FBT001
    """Destroy and recreate the local PostgreSQL container and volume."""
    source = get_db_source()
    if source is None:
        sys.exit("Database not configured. Run 'observer setup' first.")
    if source == "user":
        sys.exit("Database is externally managed. Use your own tools to reset it.")

    if not yes and not click.confirm("This will destroy ALL observer data. Continue?"):
        click.echo("Aborted.")
        return

    try:
        runtime = detect_runtime()
    except ContainerRuntimeNotFoundError:
        sys.exit("Neither 'docker' nor 'podman' found on PATH.")

    try:
        status = inspect_container(runtime)
        if status:
            if status.running:
                click.echo(f"Stopping '{constants.DB_CONTAINER_NAME}'...")
                stop_container(runtime)
            click.echo(f"Removing '{constants.DB_CONTAINER_NAME}'...")
            remove_container(runtime)

        if volume_exists(runtime):
            click.echo(f"Removing volume '{constants.DB_VOLUME_NAME}'...")
            remove_volume(runtime)

    except RuntimeError as exc:
        sys.exit(str(exc))

    _ensure_container_ready(runtime, message="PostgreSQL is ready. Database has been reset.")


@db.command("status")
def db_status() -> None:
    """Show database configuration and status."""
    source = get_db_source()
    if source is None:
        click.echo("Database not configured.")
        click.echo("Run 'observer setup' to configure.")
        return

    pg_url = get_pg_url()
    click.echo(f"Source: {source}")
    click.echo(f"URL:    {_mask_pg_url(pg_url) if pg_url else '(not set)'}")

    if source == "user":
        return

    try:
        runtime = detect_runtime()
    except ContainerRuntimeNotFoundError:
        click.echo("Container runtime: not found (docker/podman)")
        return

    status = inspect_container(runtime)

    if status is None:
        click.echo(f"Container '{constants.DB_CONTAINER_NAME}' not found.")
        click.echo("Run 'observer db up' to create it.")
        return

    state = "running" if status.running else status.status_text
    click.echo(f"Container: {status.container_name}  ({state})")
    click.echo(f"  Runtime: {status.runtime}")
    click.echo(f"  Port:    {status.port}")
    click.echo(f"  Volume:  {status.volume}")


@main.command()
@click.option("--foreground", "-f", is_flag=True, help="Run in the foreground.")
@click.option("--no-viz", is_flag=True, help="Don't start the visualization dashboard.")
def start(foreground: bool, no_viz: bool) -> None:  # noqa: FBT001
    """Start the observer daemon."""
    daemon = Daemon(pid_file=constants.PID_FILE, enable_viz=not no_viz)

    if daemon.check_running():
        sys.exit("Observer is already running.")

    _ensure_db()

    constants.OBSERVER_DIR.mkdir(parents=True, exist_ok=True)

    if foreground:
        click.echo("Observer running in foreground.")
    else:
        click.echo("Observer started.")

    if not no_viz:
        click.echo(f"  Dashboard: http://{constants.VIZ_HOST}:{constants.VIZ_PORT}")

    daemon.run(foreground=foreground)


@main.command()
@click.option("--timeout", "-t", default=10, show_default=True, help="Seconds to wait.")
def stop(timeout: int) -> None:
    """Stop the observer daemon."""
    daemon = Daemon(pid_file=constants.PID_FILE)
    pid = daemon.check_running()

    if pid is None:
        sys.exit("Observer is not running.")

    os.kill(pid, signal.SIGTERM)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not Daemon.is_process_running(pid):
            daemon._pid_file.unlink(missing_ok=True)
            click.echo("Observer stopped.")
            return
        time.sleep(0.1)

    sys.exit(f"Observer (pid={pid}) did not stop within {timeout}s.")


def _mask_pg_url(url: str) -> str:
    """Return the URL with the password replaced by *** for safe display."""
    parsed = urlparse(url)
    if not parsed.password:
        return url
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    netloc = f"{parsed.username}:***@{host}" if parsed.username else f"***@{host}"
    return urlunparse(parsed._replace(netloc=netloc))


@main.command()
def status() -> None:
    """Show observer daemon status."""
    daemon = Daemon(pid_file=constants.PID_FILE)
    pid = daemon.check_running()

    if pid is None:
        click.echo("Observer is not running.")
        sys.exit(3)

    click.echo(f"Observer is running (pid={pid}).")
    click.echo(f"  Configured Mode: {get_mode()}")
    pg_url = os.environ.get("OBSERVER_PG_URL") or get_pg_url() or "(not set)"
    click.echo(f"  PG:   {_mask_pg_url(pg_url)}")
    click.echo(f"  Log:  {constants.LOG_FILE}")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        notebook_up = s.connect_ex((constants.VIZ_HOST, constants.VIZ_PORT)) == 0
    if notebook_up:
        click.echo(f"  Notebook: http://{constants.VIZ_HOST}:{constants.VIZ_PORT}")
    else:
        click.echo("  Notebook: not running")


@main.command()
@click.option("-n", "lines", default=20, show_default=True, help="Number of lines.")
@click.option("--follow", "-f", is_flag=True, help="Follow log output.")
def logs(lines: int, follow: bool) -> None:  # noqa: FBT001
    """Show observer daemon logs."""
    log_file = constants.LOG_FILE

    if not log_file.exists():
        sys.exit(f"Log file not found: {log_file}")

    args = ["tail", f"-n{lines}"]
    if follow:
        args.append("-f")
    args.append(str(log_file))

    os.execvp("tail", args)


@main.command()
@click.option("--port", "-p", default=constants.VIZ_PORT, show_default=True, help="Port to serve on.")
@click.option("--host", default=constants.VIZ_HOST, show_default=True, help="Host to bind to.")
@click.option("--headless", is_flag=True, help="Don't open browser automatically.")
def viz(port: int, host: str, headless: bool) -> None:  # noqa: FBT001
    """Launch the observer visualization dashboard (standalone)."""
    try:
        import marimo  # noqa: F401, PLC0415
    except ImportError:
        sys.exit("marimo is not installed. Reinstall observer with:\n  uv tool install -e ./observer --force")

    app_path = files("observer.viz").joinpath("app.py")

    args = [
        sys.executable,
        "-m",
        "marimo",
        "run",
        str(app_path),
        "--host",
        host,
        "--port",
        str(port),
    ]
    if headless:
        args.append("--headless")

    click.echo(f"Observer dashboard: http://{host}:{port}")
    os.execvp(args[0], args)


@main.command()
def mcp() -> None:
    """Start the MCP server for semantic search over observer memory."""
    from observer.mcp.server import main as mcp_main  # noqa: PLC0415

    mcp_main()


@main.command()
@click.argument("target", required=False, type=click.Choice(["on", "off"]))
def mode(target: str | None) -> None:
    """Show or set the observer processing mode.

    \b
    on   — full pipeline (extraction, embedding, indexing)
    off  — ingestion only (no LLM calls)
    """
    _mode_descriptions = {
        "on": "Full pipeline (extraction, embedding, indexing)",
        "off": "Ingestion only (no LLM calls)",
    }
    current = get_mode()

    if target is None:
        click.echo(f"Current mode: {current}")
        click.echo(f"  {_mode_descriptions[current]}")
        return

    if target == current:
        click.echo(f"Already in {current} mode.")
        return

    set_mode(target)
    click.echo(f"Switched to {target} mode.")

    daemon = Daemon(pid_file=constants.PID_FILE)
    if daemon.check_running():
        click.echo("Restart the daemon for changes to take effect:")
        click.echo("  observer stop && observer start")


@main.command()
def setup() -> None:
    """Configure observer: set PostgreSQL URL and verify the connection."""
    db_choice = questionary.select(
        "Database source:",
        choices=[
            questionary.Choice("Local container (Docker/Podman)", value="container"),
            questionary.Choice("External PostgreSQL URL", value="user"),
        ],
    ).ask()
    if db_choice is None:
        sys.exit(1)

    if db_choice == "container":
        url = _setup_container()
    else:
        url = _setup_external_url()

    _verify_connection(url)

    _model_choices = ["haiku", "sonnet", "opus"]
    extraction_model = questionary.select(
        "Extraction model:",
        choices=_model_choices,
        default=get_extraction_model(),
    ).ask()
    if extraction_model is None:
        sys.exit(1)

    summary_model = questionary.select(
        "Summary model:",
        choices=_model_choices,
        default=get_summary_model(),
    ).ask()
    if summary_model is None:
        sys.exit(1)

    mode_choice = questionary.select(
        "Processing mode:",
        choices=[
            questionary.Choice("On (extraction, embedding, indexing)", value="on"),
            questionary.Choice("Off (ingestion only, no LLM calls)", value="off"),
        ],
        default=get_mode(),
    ).ask()
    if mode_choice is None:
        sys.exit(1)

    set_pg_url(url)
    set_db_source(db_choice)
    set_extraction_model(extraction_model)
    set_summary_model(summary_model)
    set_mode(mode_choice)
    click.echo(f"\nConfiguration saved → {CONFIG_FILE}")

    daemon = Daemon(pid_file=constants.PID_FILE)
    if click.confirm("\nStart observer daemon?", default=True):
        if daemon.check_running():
            click.echo("Daemon is already running.")
        else:
            constants.OBSERVER_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(
                ["observer", "start"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(10):
                time.sleep(0.2)
                if daemon.check_running():
                    click.echo("Daemon started.")
                    break
            else:
                click.echo("Daemon may still be starting — check: observer status")


def _ensure_container_ready(runtime: str, *, message: str = "PostgreSQL is ready.") -> None:
    """Ensure the container is running and PostgreSQL accepts connections, or exit."""
    status = inspect_container(runtime)
    if status and status.running:
        label = "Checking"
    elif status:
        label = "Restarting"
    else:
        label = "Creating"

    click.echo(f"{label} container '{constants.DB_CONTAINER_NAME}'...", nl=False)

    try:
        ready = ensure_running(runtime)
    except RuntimeError as exc:
        click.echo(f" failed.\n  {exc}")
        sys.exit(1)

    if ready:
        click.echo(f" {message}")
    else:
        click.echo(" timed out.")
        click.echo(container_logs(runtime, lines=10))
        sys.exit(1)


def _ensure_db() -> None:
    """Ensure the database is available before starting the daemon."""
    source = get_db_source()
    if source is None:
        sys.exit("Database not configured. Run 'observer setup' first.")
    if source != "container":
        return

    try:
        runtime = detect_runtime()
    except ContainerRuntimeNotFoundError:
        sys.exit("Neither 'docker' nor 'podman' found on PATH.")

    _ensure_container_ready(runtime)


def _setup_container() -> str:
    """Provision a local PostgreSQL container, return the connection URL."""
    try:
        runtime = detect_runtime()
    except ContainerRuntimeNotFoundError:
        sys.exit("Neither 'docker' nor 'podman' found on PATH.")

    _ensure_container_ready(runtime)
    return constants.DB_PG_URL


def _setup_external_url() -> str:
    """Prompt for an external PostgreSQL URL, return it."""
    existing = None
    if get_db_source() == "user":
        existing = get_pg_url()

    if existing:
        click.echo(f"Current URL: {_mask_pg_url(existing)}")

    default_url = existing or "postgresql://localhost/observer"
    url: str = click.prompt("PostgreSQL URL", default=default_url)
    return url


def _verify_connection(url: str) -> None:
    """Test PostgreSQL connectivity and ensure pgvector is available."""
    engine = create_engine(url)
    try:
        click.echo("  Connecting...", nl=False)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        click.echo(" OK")

        click.echo("  Checking pgvector...", nl=False)
        with engine.connect() as conn:
            row = conn.execute(text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")).fetchone()
            if row is None:
                click.echo(" NOT FOUND")
                click.echo(
                    "  pgvector is not installed on this PostgreSQL server.\n"
                    "  Install it first: https://github.com/pgvector/pgvector#installation"
                )
                sys.exit(1)
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        click.echo(" OK")
    except Exception as e:
        click.echo(f" FAILED\n  {e}")
        sys.exit(1)
    finally:
        engine.dispose()


@main.command()
def register() -> None:
    """Register a Claude Code session (called by SessionStart hook)."""
    from observer.services.registration import (  # noqa: PLC0415
        HookInput,
        ensure_daemon_running,
        register_session,
    )

    raw = sys.stdin.read()
    if not raw.strip():
        sys.exit("No input received on stdin.")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON on stdin: {e}")

    if not isinstance(data, dict):
        sys.exit("stdin JSON must be an object/dict")

    required = {"session_id", "transcript_path", "cwd"}
    missing = required - data.keys()
    if missing:
        sys.exit(f"Missing required fields in stdin JSON: {', '.join(sorted(missing))}")

    hook_input = HookInput(
        session_id=data["session_id"],
        transcript_path=data["transcript_path"],
        cwd=data["cwd"],
    )

    try:
        result = register_session(hook_input)
    except (RegistrationError, ValueError) as e:
        sys.exit(str(e))

    if result.created:
        click.echo(f"Registered transcript {result.transcript.session_id}")
    else:
        click.echo(f"Session {result.transcript.session_id} already registered")

    pid = ensure_daemon_running()
    if pid:
        click.echo(f"Daemon running (pid={pid})")
