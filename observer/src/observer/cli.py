"""CLI entry point for the observer."""

import json
import os
import sys
from importlib.resources import files
from urllib.parse import urlparse, urlunparse

import click
import questionary
from sqlalchemy import create_engine, text

from observer import constants
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
    """Observer — monitors Claude Code transcripts."""


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


@db.command()
def migrate() -> None:
    """Run pending database schema migrations."""
    from observer.services.migrations import (  # noqa: PLC0415
        get_current_version,
        get_pending,
        run_pending,
    )

    pg_url = get_pg_url()
    if not pg_url:
        sys.exit("Database not configured. Run 'observer setup' first.")

    engine = create_engine(pg_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        sys.exit(f"Cannot connect to database: {e}")

    current = get_current_version(engine)
    pending = get_pending(engine)

    if not pending:
        click.echo(f"Schema is up to date (version {current}).")
        engine.dispose()
        return

    click.echo(f"Current schema version: {current}")
    click.echo(f"Pending migrations: {len(pending)}")
    for m in pending:
        click.echo(f"  {m.version:03d}: {m.description}")

    click.echo()
    applied = run_pending(engine)

    # After migrations, run create_all to pick up new tables/columns
    from observer.services.db import Base  # noqa: PLC0415

    Base.metadata.create_all(engine)

    click.echo(f"\nApplied {len(applied)} migration(s). Schema is now at version {applied[-1].version}.")
    engine.dispose()


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
@click.option("-n", "lines", default=20, show_default=True, help="Number of lines.")
@click.option("--follow", "-f", is_flag=True, help="Follow log output.")
def logs(lines: int, follow: bool) -> None:  # noqa: FBT001
    """Show observer logs."""
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
def ingest() -> None:
    """Ingest transcript events from a hook. Reads JSON from stdin.

    Synchronous entry point for PreCompact/SessionEnd hooks.
    Registers the session (if needed), parses new JSONL events,
    and groups them into work items.
    """
    from observer.pipeline.parser import TranscriptParser  # noqa: PLC0415
    from observer.pipeline.refining.grouping import EventGrouper  # noqa: PLC0415
    from observer.services.db import Database  # noqa: PLC0415
    from observer.services.registration import (  # noqa: PLC0415
        HookInput,
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

    transcript = result.transcript

    # Parse new JSONL events from cursor_offset
    ingested = TranscriptParser().ingest(transcript)

    # Group raw events into work items (pure logic, no LLM)
    db = Database()
    grouped = EventGrouper.group_pending(db)

    click.echo(f"session={transcript.session_id} ingested={ingested} grouped={grouped}")


@main.command()
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
def reprocess(yes: bool) -> None:  # noqa: FBT001
    """Clear derived data and re-run the full pipeline for all transcripts.

    Keeps raw_events and transcripts intact. Clears work_items,
    transcript_events, and artifacts, resets raw_event status to PENDING,
    then runs group → refine → extract → embed for each transcript.
    """
    from observer.data.enums import RawEventStatus  # noqa: PLC0415
    from observer.data.schemas import (  # noqa: PLC0415
        ArtifactSchema,
        RawEventSchema,
        TranscriptEventSchema,
        TranscriptSchema,
        WorkItemSchema,
    )
    from observer.pipeline.extraction import TranscriptExtractor  # noqa: PLC0415
    from observer.pipeline.indexing import SearchIndexer  # noqa: PLC0415
    from observer.pipeline.refining import EventRefiner  # noqa: PLC0415
    from observer.services.db import Database  # noqa: PLC0415
    from observer.services.logger import configure_logging  # noqa: PLC0415

    configure_logging(foreground=True)

    db = Database()

    # Count what we're about to reprocess
    with db.session() as session:
        transcript_count = session.query(TranscriptSchema).count()
        raw_event_count = session.query(RawEventSchema).count()

    if transcript_count == 0:
        click.echo("No transcripts found. Nothing to reprocess.")
        return

    click.echo(f"Transcripts: {transcript_count}")
    click.echo(f"Raw events:  {raw_event_count}")
    click.echo("\nThis will clear all work_items, transcript_events, and artifacts,")
    click.echo("then re-run the full pipeline (group → refine → extract → embed).")

    if not yes and not click.confirm("\nProceed?"):
        click.echo("Aborted.")
        return

    # Phase 0: Clear derived tables and reset raw_event status
    click.echo("\nClearing derived data...")
    with db.session() as session:
        session.query(ArtifactSchema).delete()
        session.query(TranscriptEventSchema).delete()
        session.query(WorkItemSchema).delete()
        session.execute(RawEventSchema.__table__.update().values(processed=RawEventStatus.PENDING))
    click.echo("  Cleared work_items, transcript_events, artifacts")
    click.echo("  Reset raw_events to PENDING")

    # Phase 1: Group raw events into work items, then refine into transcript events
    click.echo("\nGrouping and refining...")
    refined = EventRefiner.refine_pending(db)
    click.echo(f"  Refined {refined} work items")

    # Phase 2: Extract per transcript
    click.echo("\nExtracting artifacts...")
    with db.session() as session:
        transcript_ids = [row[0] for row in session.query(TranscriptSchema.id).all()]

    extracted = 0
    for tid in transcript_ids:
        count = TranscriptExtractor.extract_transcript(db, tid)
        extracted += count

    click.echo(f"  Extracted {extracted} artifact sections across {len(transcript_ids)} transcripts")

    # Phase 3: Embed all artifacts
    click.echo("\nEmbedding artifacts...")
    SearchIndexer.index_pending(db)
    click.echo("  Embedding complete")

    click.echo("\nReprocessing complete.")


@main.command()
@click.argument("session_id")
def process(session_id: str) -> None:
    """Run background processing for a session. Refine, extract, embed.

    Called as a detached background process by the hook script.
    Runs the full LLM pipeline: refine work_items into transcript_events,
    extract structured artifacts, and embed for semantic search.
    """
    from observer.data.transcript import Transcript  # noqa: PLC0415
    from observer.pipeline.extraction import TranscriptExtractor  # noqa: PLC0415
    from observer.pipeline.indexing import SearchIndexer  # noqa: PLC0415
    from observer.pipeline.refining import EventRefiner  # noqa: PLC0415
    from observer.services.config import get_mode  # noqa: PLC0415
    from observer.services.db import Database  # noqa: PLC0415
    from observer.services.logger import configure_logging  # noqa: PLC0415

    configure_logging()

    transcript = Transcript.get_by_session_id(session_id)
    if transcript is None:
        sys.exit(f"No transcript found for session {session_id}")

    if get_mode() == "off":
        return

    db = Database()
    try:
        # Phase 1: Refine work_items → transcript_events (LLM calls)
        EventRefiner.refine_pending(db, transcript_id=transcript.id)

        # Phase 2: Extract transcript_events → artifacts (single LLM call)
        TranscriptExtractor.extract_transcript(db, transcript.id)

        # Phase 3: Embed artifacts → pgvector
        SearchIndexer.index_pending(db, transcript_id=transcript.id)
    finally:
        db.close()
