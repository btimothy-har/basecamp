"""Migration 002: Drop last_mtime from transcripts.

The last_mtime column was used by the polling daemon to detect file changes.
With the move to hook-based ingestion, file mtime tracking is no longer needed.
"""

from sqlalchemy import Engine, text

from observer.services.migrations import migration


@migration(version=2, description="Drop last_mtime column from transcripts")
def run(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE transcripts DROP COLUMN IF EXISTS last_mtime"))
