"""CLI entry point for the pi_observer."""
# ruff: noqa: PLC0415

import json
import logging
import os
import sys

import click
from pi_observer import constants
from pi_observer.cli import recall
from pi_observer.settings import settings
from pi_observer.ui import console


@click.group()
def main() -> None:
    """Observer — monitors Claude Code transcripts."""


@main.group()
def db() -> None:
    """Database management commands."""


@db.command()
def status() -> None:
    """Show database status."""
    from pi_observer.constants import OBSERVER_CHROMA_DIR as CHROMA_DIR
    from pi_observer.constants import OBSERVER_DB_PATH as DB_PATH

    console.print(f"SQLite:   [blue]{DB_PATH}[/blue]")
    console.print(f"  Exists: {DB_PATH.exists()}")
    console.print(f"ChromaDB: [blue]{CHROMA_DIR}[/blue]")
    console.print(f"  Exists: {CHROMA_DIR.exists()}")

    if DB_PATH.exists():
        from pi_observer.services.db import Database

        try:
            db_inst = Database()
            with db_inst.session() as session:
                from pi_observer.data.schemas import ArtifactSchema, TranscriptSchema

                transcripts = session.query(TranscriptSchema).count()
                artifacts = session.query(ArtifactSchema).count()
            console.print(f"  Transcripts: {transcripts}")
            console.print(f"  Artifacts:   {artifacts}")
        except Exception as e:
            console.print(f"  [red]Error:[/red] {e}")


@db.command()
def migrate() -> None:
    """Run pending database schema migrations."""
    from pi_observer.services.db import Database
    from pi_observer.services.migrations import (
        get_current_version,
        get_pending,
        run_pending,
    )

    db_inst = Database()
    engine = db_inst._engine

    current = get_current_version(engine)
    pending = get_pending(engine)

    if not pending:
        console.print(f"[green]✓[/green] Schema is up to date (version {current}).")
        return

    console.print(f"Current schema version: {current}")
    console.print(f"Pending migrations: {len(pending)}")
    for m in pending:
        console.print(f"  {m.version:03d}: {m.description}")

    console.print()
    applied = run_pending(engine)

    from pi_observer.services.db import Base

    Base.metadata.create_all(engine)

    version = applied[-1].version
    console.print(f"\n[green]✓[/green] Applied {len(applied)} migration(s). Schema is now at version {version}.")


@db.command("reset")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
def db_reset(yes: bool) -> None:  # noqa: FBT001
    """Destroy and recreate the local database."""
    from pi_observer.constants import OBSERVER_CHROMA_DIR as CHROMA_DIR
    from pi_observer.constants import OBSERVER_DB_PATH as DB_PATH

    if not yes and not click.confirm("This will destroy ALL observer data. Continue?"):
        console.print("Aborted.")
        return

    if DB_PATH.exists():
        DB_PATH.unlink()
        console.print(f"  Removed [dim]{DB_PATH}[/dim]")

    # Remove WAL/SHM files if present
    for suffix in ("-wal", "-shm"):
        wal = DB_PATH.parent / (DB_PATH.name + suffix)
        if wal.exists():
            wal.unlink()

    if CHROMA_DIR.exists():
        import shutil

        shutil.rmtree(CHROMA_DIR)
        console.print(f"  Removed [dim]{CHROMA_DIR}[/dim]")

    # Reinitialize
    from pi_observer.services.db import Database

    Database.close_if_open()
    Database()
    console.print("[green]✓[/green] Database reset complete.")


@main.command()
@click.option("-n", "lines", default=20, show_default=True, help="Number of lines.")
@click.option("--follow", "-f", is_flag=True, help="Follow log output.")
def logs(lines: int, follow: bool) -> None:  # noqa: FBT001
    """Show observer logs."""
    log_file = constants.OBSERVER_LOG_FILE

    if not log_file.exists():
        sys.exit(f"Log file not found: {log_file}")

    args = ["tail", f"-n{lines}"]
    if follow:
        args.append("-f")
    args.append(str(log_file))

    os.execvp("tail", args)


@main.group()
def config() -> None:
    """Observer configuration commands."""


@config.command("show")
def config_show() -> None:
    """Show observer configuration."""
    console.print(f"Mode:             [bold]{settings.mode}[/bold]")
    console.print(f"Extraction model: [bold]{settings.extraction_model}[/bold]")
    console.print(f"Summary model:    [bold]{settings.summary_model}[/bold]")
    console.print(f"Config:           [dim]{settings.path}[/dim]")


@config.group("set")
def config_set() -> None:
    """Set observer configuration values."""


@config_set.command("mode")
@click.argument("value", type=click.Choice(["on", "off"]))
def config_set_mode(value: str) -> None:
    """Set observer processing mode."""
    settings.mode = value
    console.print(f"[green]✓[/green] Mode → [bold]{value}[/bold]")


@config_set.command("extraction-model")
@click.argument("value")
def config_set_extraction_model(value: str) -> None:
    """Set model used for artifact extraction."""
    settings.extraction_model = value
    console.print(f"[green]✓[/green] Extraction model → [bold]{value}[/bold]")


@config_set.command("summary-model")
@click.argument("value")
def config_set_summary_model(value: str) -> None:
    """Set model used for summaries."""
    settings.summary_model = value
    console.print(f"[green]✓[/green] Summary model → [bold]{value}[/bold]")


@main.command()
@click.option(
    "--extraction-model",
    "-e",
    default=None,
    help="Model for extraction (e.g. anthropic:claude-sonnet-4-20250514)",
)
@click.option(
    "--summary-model",
    "-s",
    default=None,
    help="Model for summaries (e.g. anthropic:claude-3-5-haiku-latest)",
)
@click.option("--mode", "-m", "target_mode", type=click.Choice(["on", "off"]), default=None, help="Processing mode")
def setup(extraction_model: str | None, summary_model: str | None, target_mode: str | None) -> None:
    """Configure observer: initialize database and set model preferences.

    \b
    Models use pydantic-ai's provider:model format:
      anthropic:claude-3-5-haiku-latest
      anthropic:claude-sonnet-4-20250514
      openai:gpt-4o-mini
      openai:gpt-4o

    With no flags, shows current config and initializes the database.
    """
    from pi_observer.constants import OBSERVER_CHROMA_DIR as CHROMA_DIR
    from pi_observer.constants import OBSERVER_DB_PATH as DB_PATH

    # Ensure directories exist
    constants.OBSERVER_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize SQLite + ChromaDB
    from pi_observer.services.db import Database

    Database.close_if_open()
    Database()

    from pi_observer.services.chroma import get_collection

    get_collection()

    # Apply any provided settings
    obs = settings
    changed = False
    if extraction_model is not None:
        obs.extraction_model = extraction_model
        changed = True
    if summary_model is not None:
        obs.summary_model = summary_model
        changed = True
    if target_mode is not None:
        obs.mode = target_mode
        changed = True

    # Show current config
    console.print(f"Database:         [blue]{DB_PATH}[/blue]")
    console.print(f"ChromaDB:         [blue]{CHROMA_DIR}[/blue]")
    console.print(f"Extraction model: [bold]{obs.extraction_model}[/bold]")
    console.print(f"Summary model:    [bold]{obs.summary_model}[/bold]")
    console.print(f"Mode:             [bold]{obs.mode}[/bold]")
    console.print(f"Config:           [dim]{settings.path}[/dim]")

    if changed:
        console.print("\n[green]✓[/green] Configuration updated.")


@main.command()
@click.option("--process", "run_process", is_flag=True, help="Also run the LLM pipeline (refine, extract, embed).")
def ingest(run_process: bool) -> None:  # noqa: FBT001
    """Ingest transcript events from a hook. Reads JSON from stdin.

    Registers the session (if needed), parses new JSONL events,
    and groups them into work items. With --process, also runs the
    LLM pipeline (refine → extract → embed) after ingestion.
    """
    from pi_observer.pipeline.grouping import EventGrouper
    from pi_observer.pipeline.parser import TranscriptParser
    from pi_observer.services.db import Database
    from pi_observer.services.logger import configure_logging
    from pi_observer.services.registration import (
        HookInput,
        register_session,
    )

    configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("ingest called%s", " --process" if run_process else "")

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
        repo_name=data.get("repo_name"),
        repo_root=data.get("repo_root"),
    )

    try:
        result = register_session(hook_input)
        transcript = result.transcript

        db_inst = Database()
        ingested = TranscriptParser().ingest(transcript)
        grouped = EventGrouper.group_pending(db_inst, transcript.id)
        logger.info("session=%s ingested=%d grouped=%d", transcript.session_id, ingested, grouped)

        if run_process:
            from pi_observer.pipeline.extraction import TranscriptExtractor
            from pi_observer.pipeline.indexing import SearchIndexer
            from pi_observer.pipeline.refinement import EventRefiner

            if settings.mode != "off":
                EventRefiner.refine_pending(db_inst, transcript_id=transcript.id)
                TranscriptExtractor.extract_transcript(db_inst, transcript.id)
                SearchIndexer.index_pending(db_inst, transcript_id=transcript.id)
    except SystemExit:
        raise
    except Exception:
        logger.exception("Ingestion failed for session %s", hook_input.session_id)
        sys.exit(1)


@main.command()
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
def reprocess(yes: bool) -> None:  # noqa: FBT001
    """Clear derived data and re-run the full pipeline for all transcripts.

    Keeps raw_events and transcripts intact. Clears work_items,
    transcript_events, and artifacts, resets raw_event status to PENDING,
    then runs group → refine → extract → embed for each transcript.
    """
    from pi_observer.data.enums import RawEventStatus
    from pi_observer.data.schemas import (
        ArtifactSchema,
        RawEventSchema,
        TranscriptEventSchema,
        TranscriptSchema,
        WorkItemSchema,
    )
    from pi_observer.pipeline.extraction import TranscriptExtractor
    from pi_observer.pipeline.grouping import EventGrouper
    from pi_observer.pipeline.indexing import SearchIndexer
    from pi_observer.pipeline.refinement import EventRefiner
    from pi_observer.services.chroma import COLLECTION_NAME, get_client
    from pi_observer.services.db import Database
    from pi_observer.services.logger import configure_logging

    configure_logging(foreground=True)

    db_inst = Database()

    # Count what we're about to reprocess
    with db_inst.session() as session:
        transcript_count = session.query(TranscriptSchema).count()
        raw_event_count = session.query(RawEventSchema).count()

    if transcript_count == 0:
        console.print("No transcripts found. Nothing to reprocess.")
        return

    console.print(f"Transcripts: {transcript_count}")
    console.print(f"Raw events:  {raw_event_count}")
    console.print("\nThis will clear all work_items, transcript_events, and artifacts,")
    console.print("then re-run the full pipeline (group → refine → extract → embed).")

    if not yes and not click.confirm("\nProceed?"):
        console.print("Aborted.")
        return

    # Phase 0: Clear derived tables, reset raw_event status, clear ChromaDB
    console.print("\n[bold]Clearing derived data...[/bold]")
    with db_inst.session() as session:
        session.query(ArtifactSchema).delete()
        session.query(TranscriptEventSchema).delete()
        session.query(WorkItemSchema).delete()
        session.execute(RawEventSchema.__table__.update().values(processed=RawEventStatus.PENDING))
    console.print("  Cleared work_items, transcript_events, artifacts")
    console.print("  Reset raw_events to PENDING")

    # Clear ChromaDB collection
    try:
        get_client().delete_collection(COLLECTION_NAME)
    except Exception:
        pass  # Collection may not exist yet
    console.print("  Cleared ChromaDB embeddings")

    with db_inst.session() as session:
        transcript_ids = [row[0] for row in session.query(TranscriptSchema.id).all()]

    # Phase 1: Group raw events into work items per transcript
    console.print("\n[bold]Grouping...[/bold]")
    grouped = 0
    for tid in transcript_ids:
        grouped += EventGrouper.group_pending(db_inst, tid)
    console.print(f"  Grouped {grouped} work items")

    # Phase 2: Refine work items into transcript events
    console.print("\n[bold]Refining...[/bold]")
    refined = EventRefiner.refine_pending(db_inst)
    console.print(f"  Refined {refined} work items")

    # Phase 3: Extract per transcript
    console.print("\n[bold]Extracting artifacts...[/bold]")

    extracted = 0
    for tid in transcript_ids:
        count = TranscriptExtractor.extract_transcript(db_inst, tid)
        extracted += count

    console.print(f"  Extracted {extracted} artifact sections across {len(transcript_ids)} transcripts")

    # Phase 4: Embed all artifacts
    console.print("\n[bold]Embedding artifacts...[/bold]")
    SearchIndexer.index_pending(db_inst)
    console.print("  Embedding complete")

    console.print("\n[green]✓[/green] Reprocessing complete.")


main.add_command(recall.main, name="recall")
