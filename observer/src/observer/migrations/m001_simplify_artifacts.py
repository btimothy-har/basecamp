"""Migration 001: Simplify artifacts schema.

Originally replaced the per-event artifact + separate search_index model with
transcript-level section artifacts. Now a no-op — fresh SQLite installs get
the latest schema from create_all().
"""

from sqlalchemy import Engine

from observer.services.migrations import migration


@migration(version=1, description="Simplify artifacts: drop search_index, rebuild artifacts table")
def run(engine: Engine) -> None:
    pass  # No-op: SQLite installs start with the latest schema.
