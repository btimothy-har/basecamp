"""CLI entry point for the observer."""
# ruff: noqa: PLC0415

import json
import logging
import os
import sys

import click

from observer import constants
from observer.services.config import (
    CONFIG_FILE,
    get_extraction_model,
    get_mode,
    get_summary_model,
    set_extraction_model,
    set_mode,
    set_summary_model,
)


@click.group()
def main() -> None:
    """Observer — monitors Claude Code transcripts."""


@main.group()
def db() -> None:
    """Database management commands."""


@db.command()
def status() -> None:
    """Show database status."""
    from observer.constants import CHROMA_DIR, DB_PATH

    click.echo(f"SQLite:   {DB_PATH}")
    click.echo(f"  Exists: {DB_PATH.exists()}")
    click.echo(f"ChromaDB: {CHROMA_DIR}")
    click.echo(f"  Exists: {CHROMA_DIR.exists()}")

    if DB_PATH.exists():
        from observer.services.db import Database

        try:
            db_inst = Database()
            with db_inst.session() as session:
                from observer.data.schemas import ArtifactSchema, TranscriptSchema

                transcripts = session.query(TranscriptSchema).count()
                artifacts = session.query(ArtifactSchema).count()
            click.echo(f"  Transcripts: {transcripts}")
            click.echo(f"  Artifacts:   {artifacts}")
        except Exception as e:
            click.echo(f"  Error: {e}")


@db.command()
def migrate() -> None:
    """Run pending database schema migrations."""
    from observer.services.db import Database
    from observer.services.migrations import (
        get_current_version,
        get_pending,
        run_pending,
    )

    db_inst = Database()
    engine = db_inst._engine

    current = get_current_version(engine)
    pending = get_pending(engine)

    if not pending:
        click.echo(f"Schema is up to date (version {current}).")
        return

    click.echo(f"Current schema version: {current}")
    click.echo(f"Pending migrations: {len(pending)}")
    for m in pending:
        click.echo(f"  {m.version:03d}: {m.description}")

    click.echo()
    applied = run_pending(engine)

    from observer.services.db import Base

    Base.metadata.create_all(engine)

    click.echo(f"\nApplied {len(applied)} migration(s). Schema is now at version {applied[-1].version}.")


@db.command("reset")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
def db_reset(yes: bool) -> None:  # noqa: FBT001
    """Destroy and recreate the local database."""
    from observer.constants import CHROMA_DIR, DB_PATH

    if not yes and not click.confirm("This will destroy ALL observer data. Continue?"):
        click.echo("Aborted.")
        return

    if DB_PATH.exists():
        DB_PATH.unlink()
        click.echo(f"Removed {DB_PATH}")

    # Remove WAL/SHM files if present
    for suffix in ("-wal", "-shm"):
        wal = DB_PATH.parent / (DB_PATH.name + suffix)
        if wal.exists():
            wal.unlink()

    if CHROMA_DIR.exists():
        import shutil

        shutil.rmtree(CHROMA_DIR)
        click.echo(f"Removed {CHROMA_DIR}")

    # Reinitialize
    from observer.services.db import Database

    Database.close_if_open()
    Database()
    click.echo("Database reset complete.")


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
    from observer.constants import CHROMA_DIR, DB_PATH

    # Ensure directories exist
    constants.BASECAMP_DIR.mkdir(parents=True, exist_ok=True)
    constants.OBSERVER_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize SQLite + ChromaDB
    from observer.services.db import Database

    Database.close_if_open()
    Database()

    from observer.services.chroma import get_collection

    get_collection()

    # Apply any provided settings
    changed = False
    if extraction_model is not None:
        set_extraction_model(extraction_model)
        changed = True
    if summary_model is not None:
        set_summary_model(summary_model)
        changed = True
    if target_mode is not None:
        set_mode(target_mode)
        changed = True

    # Show current config
    click.echo(f"Database:         {DB_PATH}")
    click.echo(f"ChromaDB:         {CHROMA_DIR}")
    click.echo(f"Extraction model: {get_extraction_model()}")
    click.echo(f"Summary model:    {get_summary_model()}")
    click.echo(f"Mode:             {get_mode()}")
    click.echo(f"Config:           {CONFIG_FILE}")

    if changed:
        click.echo("\nConfiguration updated.")


@main.command()
@click.option("--process", "run_process", is_flag=True, help="Also run the LLM pipeline (refine, extract, embed).")
def ingest(run_process: bool) -> None:  # noqa: FBT001
    """Ingest transcript events from a hook. Reads JSON from stdin.

    Registers the session (if needed), parses new JSONL events,
    and groups them into work items. With --process, also runs the
    LLM pipeline (refine → extract → embed) after ingestion.
    """
    from observer.pipeline.grouping import EventGrouper
    from observer.pipeline.parser import TranscriptParser
    from observer.services.db import Database
    from observer.services.logger import configure_logging
    from observer.services.registration import (
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
    )

    try:
        result = register_session(hook_input)
        transcript = result.transcript

        db_inst = Database()
        ingested = TranscriptParser().ingest(transcript)
        grouped = EventGrouper.group_pending(db_inst, transcript.id)
        logger.info("session=%s ingested=%d grouped=%d", transcript.session_id, ingested, grouped)

        if run_process:
            from observer.pipeline.extraction import TranscriptExtractor
            from observer.pipeline.indexing import SearchIndexer
            from observer.pipeline.refinement import EventRefiner
            from observer.services.config import get_mode

            if get_mode() != "off":
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
    from observer.data.enums import RawEventStatus
    from observer.data.schemas import (
        ArtifactSchema,
        RawEventSchema,
        TranscriptEventSchema,
        TranscriptSchema,
        WorkItemSchema,
    )
    from observer.pipeline.extraction import TranscriptExtractor
    from observer.pipeline.grouping import EventGrouper
    from observer.pipeline.indexing import SearchIndexer
    from observer.pipeline.refinement import EventRefiner
    from observer.services.chroma import COLLECTION_NAME, get_client
    from observer.services.db import Database
    from observer.services.logger import configure_logging

    configure_logging(foreground=True)

    db_inst = Database()

    # Count what we're about to reprocess
    with db_inst.session() as session:
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

    # Phase 0: Clear derived tables, reset raw_event status, clear ChromaDB
    click.echo("\nClearing derived data...")
    with db_inst.session() as session:
        session.query(ArtifactSchema).delete()
        session.query(TranscriptEventSchema).delete()
        session.query(WorkItemSchema).delete()
        session.execute(RawEventSchema.__table__.update().values(processed=RawEventStatus.PENDING))
    click.echo("  Cleared work_items, transcript_events, artifacts")
    click.echo("  Reset raw_events to PENDING")

    # Clear ChromaDB collection
    try:
        get_client().delete_collection(COLLECTION_NAME)
    except Exception:
        pass  # Collection may not exist yet
    click.echo("  Cleared ChromaDB embeddings")

    with db_inst.session() as session:
        transcript_ids = [row[0] for row in session.query(TranscriptSchema.id).all()]

    # Phase 1: Group raw events into work items per transcript
    click.echo("\nGrouping...")
    grouped = 0
    for tid in transcript_ids:
        grouped += EventGrouper.group_pending(db_inst, tid)
    click.echo(f"  Grouped {grouped} work items")

    # Phase 2: Refine work items into transcript events
    click.echo("\nRefining...")
    refined = EventRefiner.refine_pending(db_inst)
    click.echo(f"  Refined {refined} work items")

    # Phase 3: Extract per transcript
    click.echo("\nExtracting artifacts...")

    extracted = 0
    for tid in transcript_ids:
        count = TranscriptExtractor.extract_transcript(db_inst, tid)
        extracted += count

    click.echo(f"  Extracted {extracted} artifact sections across {len(transcript_ids)} transcripts")

    # Phase 4: Embed all artifacts
    click.echo("\nEmbedding artifacts...")
    SearchIndexer.index_pending(db_inst)
    click.echo("  Embedding complete")

    click.echo("\nReprocessing complete.")
