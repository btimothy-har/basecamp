"""CLI command to migrate data from PostgreSQL to SQLite.

Copies base tables (projects, worktrees, transcripts, raw_events) from
an existing PostgreSQL observer database into the new SQLite backend,
then runs the reprocess pipeline to regenerate all derived data.

Requires psycopg2: pip install basecamp-observer[pg-migrate]
"""

import sys

import click
from sqlalchemy import create_engine, text

from observer.services.config import get_pg_url


@click.command("migrate-from-pg")
@click.option(
    "--pg-url",
    default=None,
    help="PostgreSQL URL. Defaults to stored pg_url from config.json.",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
@click.option("--skip-reprocess", is_flag=True, help="Only copy data, skip the reprocess pipeline.")
def migrate_from_pg(pg_url: str | None, yes: bool, skip_reprocess: bool) -> None:  # noqa: FBT001
    """Migrate data from PostgreSQL to SQLite + ChromaDB."""
    try:
        import psycopg2  # noqa: F401, PLC0415
    except ImportError:
        sys.exit("psycopg2 is required for migration.\nInstall it with: pip install 'basecamp-observer[pg-migrate]'")

    url = pg_url or get_pg_url()
    if not url:
        sys.exit("No PostgreSQL URL provided.\nPass --pg-url or ensure pg_url is in ~/.basecamp/observer/config.json")

    # Test PG connection
    click.echo("Connecting to PostgreSQL...")
    pg_engine = create_engine(url)
    try:
        with pg_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        sys.exit(f"Cannot connect to PostgreSQL: {e}")
    click.echo("  Connected.")

    # Count source data
    with pg_engine.connect() as conn:
        projects = conn.execute(text("SELECT count(*) FROM projects")).scalar()
        worktrees = conn.execute(text("SELECT count(*) FROM worktrees")).scalar()
        transcripts = conn.execute(text("SELECT count(*) FROM transcripts")).scalar()
        raw_events = conn.execute(text("SELECT count(*) FROM raw_events")).scalar()

    click.echo("\nSource data:")
    click.echo(f"  Projects:    {projects}")
    click.echo(f"  Worktrees:   {worktrees}")
    click.echo(f"  Transcripts: {transcripts}")
    click.echo(f"  Raw events:  {raw_events}")

    if transcripts == 0:
        click.echo("\nNo transcripts to migrate.")
        pg_engine.dispose()
        return

    if not yes and not click.confirm("\nMigrate this data to SQLite?"):
        click.echo("Aborted.")
        pg_engine.dispose()
        return

    # Initialize SQLite
    from observer.services.db import Database  # noqa: PLC0415

    Database.close_if_open()
    db = Database()

    # Copy base tables
    click.echo("\nCopying projects...")
    _copy_projects(pg_engine, db)

    click.echo("Copying worktrees...")
    _copy_worktrees(pg_engine, db)

    click.echo("Copying transcripts...")
    _copy_transcripts(pg_engine, db)

    click.echo("Copying raw events...")
    copied = _copy_raw_events(pg_engine, db)
    click.echo(f"  Copied {copied} raw events")

    pg_engine.dispose()

    if skip_reprocess:
        click.echo("\nData copied. Skipping reprocess (use 'observer reprocess' to generate derived data).")
        return

    # Run the reprocess pipeline
    click.echo("\nRunning reprocess pipeline...")
    from observer.data.schemas import TranscriptSchema  # noqa: PLC0415
    from observer.pipeline.extraction import TranscriptExtractor  # noqa: PLC0415
    from observer.pipeline.indexing import SearchIndexer  # noqa: PLC0415
    from observer.pipeline.refining import EventRefiner  # noqa: PLC0415
    from observer.pipeline.refining.grouping import EventGrouper  # noqa: PLC0415

    with db.session() as session:
        transcript_ids = [row[0] for row in session.query(TranscriptSchema.id).all()]

    click.echo("  Grouping...")
    grouped = 0
    for tid in transcript_ids:
        grouped += EventGrouper.group_pending(db, tid)
    click.echo(f"    {grouped} work items")

    click.echo("  Refining...")
    refined = EventRefiner.refine_pending(db)
    click.echo(f"    {refined} work items")

    click.echo("  Extracting...")
    extracted = 0
    for tid in transcript_ids:
        extracted += TranscriptExtractor.extract_transcript(db, tid)
    click.echo(f"    {extracted} artifacts")

    click.echo("  Embedding...")
    SearchIndexer.index_pending(db)

    click.echo("\nMigration complete.")


def _copy_projects(pg_engine, db):
    """Copy projects from PG to SQLite, skipping existing."""
    from observer.data.schemas import ProjectSchema  # noqa: PLC0415

    with pg_engine.connect() as pg_conn:
        rows = pg_conn.execute(text("SELECT id, name, repo_path FROM projects")).fetchall()

    with db.session() as session:
        existing = {r[0] for r in session.query(ProjectSchema.name).all()}
        for row in rows:
            if row[1] not in existing:
                session.add(ProjectSchema(id=row[0], name=row[1], repo_path=row[2]))
        session.flush()


def _copy_worktrees(pg_engine, db):
    """Copy worktrees from PG to SQLite, skipping existing."""
    from observer.data.schemas import WorktreeSchema  # noqa: PLC0415

    with pg_engine.connect() as pg_conn:
        rows = pg_conn.execute(text("SELECT id, project_id, label, path, branch FROM worktrees")).fetchall()

    with db.session() as session:
        existing = {r[0] for r in session.query(WorktreeSchema.path).all()}
        for row in rows:
            if row[3] not in existing:
                session.add(
                    WorktreeSchema(
                        id=row[0],
                        project_id=row[1],
                        label=row[2],
                        path=row[3],
                        branch=row[4],
                    )
                )
        session.flush()


def _copy_transcripts(pg_engine, db):
    """Copy transcripts from PG to SQLite, skipping existing."""
    from observer.data.schemas import TranscriptSchema  # noqa: PLC0415

    with pg_engine.connect() as pg_conn:
        rows = pg_conn.execute(
            text(
                "SELECT id, project_id, worktree_id, session_id, path, "
                "cursor_offset, started_at, ended_at FROM transcripts"
            )
        ).fetchall()

    with db.session() as session:
        existing = {r[0] for r in session.query(TranscriptSchema.session_id).all()}
        for row in rows:
            if row[3] not in existing:
                session.add(
                    TranscriptSchema(
                        id=row[0],
                        project_id=row[1],
                        worktree_id=row[2],
                        session_id=row[3],
                        path=row[4],
                        cursor_offset=row[5],
                        started_at=row[6],
                        ended_at=row[7],
                    )
                )
        session.flush()


def _copy_raw_events(pg_engine, db) -> int:
    """Copy raw events from PG to SQLite in batches. Returns count copied."""
    from observer.data.schemas import RawEventSchema  # noqa: PLC0415

    batch_size = 1000
    copied = 0

    with pg_engine.connect() as pg_conn:
        total = pg_conn.execute(text("SELECT count(*) FROM raw_events")).scalar()
        offset = 0

        while offset < total:
            rows = pg_conn.execute(
                text(
                    "SELECT id, transcript_id, event_type, timestamp, content, "
                    "message_uuid, 0 as processed "  # Reset to PENDING
                    "FROM raw_events ORDER BY id LIMIT :limit OFFSET :offset"
                ),
                {"limit": batch_size, "offset": offset},
            ).fetchall()

            if not rows:
                break

            with db.session() as session:
                # Check which IDs already exist
                existing_ids = set()
                row_ids = [r[0] for r in rows]
                existing_rows = session.query(RawEventSchema.id).filter(RawEventSchema.id.in_(row_ids)).all()
                existing_ids = {r[0] for r in existing_rows}

                for row in rows:
                    if row[0] not in existing_ids:
                        session.add(
                            RawEventSchema(
                                id=row[0],
                                transcript_id=row[1],
                                event_type=row[2],
                                timestamp=row[3],
                                content=row[4],
                                message_uuid=row[5],
                                processed=row[6],
                            )
                        )
                        copied += 1
                session.flush()

            offset += batch_size

    return copied
