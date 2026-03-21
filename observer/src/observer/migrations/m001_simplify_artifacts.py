"""Migration 001: Simplify artifacts schema.

Replaces the per-event artifact + separate search_index model with
transcript-level section artifacts that hold their own embeddings.

Changes:
- Drop ``search_index`` table
- Drop old ``artifacts`` table (per-event, typed by ArtifactType)
- Drop ``title``, ``summary``, ``last_summary_at`` columns from ``transcripts``
- New ``artifacts`` table is created by ``create_all()`` after migration runs
"""

from sqlalchemy import Engine, text

from observer.services.migrations import migration


@migration(version=1, description="Simplify artifacts: drop search_index, rebuild artifacts table")
def run(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS search_index CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS artifacts CASCADE"))

        # Remove summary columns that moved into artifact sections.
        # Use DO block to skip gracefully if columns were already removed.
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    ALTER TABLE transcripts DROP COLUMN IF EXISTS title;
                    ALTER TABLE transcripts DROP COLUMN IF EXISTS summary;
                    ALTER TABLE transcripts DROP COLUMN IF EXISTS last_summary_at;
                END $$;
                """
            )
        )
