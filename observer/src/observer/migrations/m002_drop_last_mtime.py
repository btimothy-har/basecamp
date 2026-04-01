"""Migration 002: Drop last_mtime from transcripts.

Originally dropped the polling-era last_mtime column. Now a no-op —
fresh SQLite installs never had this column.
"""

from sqlalchemy import Engine

from observer.services.migrations import migration


@migration(version=2, description="Drop last_mtime column from transcripts")
def run(engine: Engine) -> None:
    pass  # No-op: SQLite installs start with the latest schema.
