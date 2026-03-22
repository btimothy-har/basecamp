"""Migration 003: Add full-text search column and GIN index to artifacts.

Adds a generated tsvector column derived from the text column, with a GIN
index for fast full-text search queries alongside the existing HNSW vector
index used for semantic search.
"""

from sqlalchemy import Engine, text

from observer.services.migrations import migration


@migration(version=3, description="Add tsvector column and GIN index to artifacts")
def run(engine: Engine) -> None:
    with engine.begin() as conn:
        # Skip if artifacts table doesn't exist yet — create_all will
        # build it with the search_vector column already included.
        exists = conn.execute(text("SELECT 1 FROM information_schema.tables WHERE table_name = 'artifacts'")).fetchone()
        if not exists:
            return

        # FTS config must match SEARCH_FTS_CONFIG in constants.py
        conn.execute(
            text(
                "ALTER TABLE artifacts "
                "ADD COLUMN IF NOT EXISTS search_vector tsvector "
                "GENERATED ALWAYS AS (to_tsvector('english', text)) STORED"
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_artifacts_search_vector ON artifacts USING gin (search_vector)")
        )
