"""Migration 003: Add full-text search index.

Originally added a PostgreSQL tsvector column and GIN index. Now a no-op —
FTS5 virtual table and triggers are created by Database._init_fts().
"""

from sqlalchemy import Engine

from observer.services.migrations import migration


@migration(version=3, description="Add full-text search index")
def run(engine: Engine) -> None:
    pass  # No-op: FTS5 setup handled by Database._init_fts().
