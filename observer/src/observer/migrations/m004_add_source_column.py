"""Migration 004: Add source column to raw_events.

Distinguishes between Claude Code and pi transcript formats so
content-parsing methods can dispatch to the correct field names.
Existing rows default to 'claude'.
"""

from sqlalchemy import Engine, text

from observer.services.migrations import migration


@migration(version=4, description="Add source column to raw_events")
def run(engine: Engine) -> None:
    with engine.begin() as conn:
        # Check if column already exists (e.g. fresh install via create_all)
        result = conn.execute(text("PRAGMA table_info(raw_events)"))
        columns = {row[1] for row in result}
        if "source" not in columns:
            conn.execute(text("ALTER TABLE raw_events ADD COLUMN source TEXT NOT NULL DEFAULT 'claude'"))
