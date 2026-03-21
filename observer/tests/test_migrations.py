"""Tests for the migration runner and migration 001."""

from observer.services.db import Base
from observer.services.migrations import (
    _registry,
    _set_version,
    get_current_version,
    get_latest_version,
    get_pending,
    needs_migration,
    run_pending,
    stamp,
)
from sqlalchemy import text


class TestVersionTracking:
    """Tests for schema_version table operations."""

    def test_current_version_zero_when_no_version_table(self, db):
        with db._engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS schema_version"))
        assert get_current_version(db._engine) == 0

    def test_current_version_returns_stamped(self, db):
        assert get_current_version(db._engine) == get_latest_version()

    def test_latest_version_matches_registry(self):
        assert get_latest_version() == max(_registry)

    def test_stamp_idempotent(self, db):
        stamp(db._engine)
        stamp(db._engine)
        assert get_current_version(db._engine) == get_latest_version()


class TestPendingDetection:
    """Tests for pending migration detection."""

    def test_new_install_no_pending_after_stamp(self, db):
        stamp(db._engine)
        assert not needs_migration(db._engine)
        assert get_pending(db._engine) == []

    def test_unstamped_db_has_pending(self, db):
        # The db fixture calls Database() which stamps new installs,
        # so we need to clear the version table to simulate an upgrade.
        with db._engine.begin() as conn:
            conn.execute(text("DELETE FROM schema_version"))

        assert needs_migration(db._engine)
        assert len(get_pending(db._engine)) > 0

    def test_pending_ordered_by_version(self, db):
        with db._engine.begin() as conn:
            conn.execute(text("DELETE FROM schema_version"))

        pending = get_pending(db._engine)
        versions = [m.version for m in pending]
        assert versions == sorted(versions)


class TestRunPending:
    """Tests for running migrations."""

    def test_run_pending_returns_empty_when_current(self, db):
        applied = run_pending(db._engine)
        assert applied == []

    def test_run_pending_applies_and_updates_version(self, db):
        # Reset to version 0 to simulate an upgrade
        with db._engine.begin() as conn:
            conn.execute(text("UPDATE schema_version SET version = 0"))

        applied = run_pending(db._engine)
        assert len(applied) >= 1
        assert get_current_version(db._engine) == get_latest_version()


class TestMigration001:
    """Tests for migration 001: simplify artifacts."""

    def test_migration_registered(self):
        assert 1 in _registry
        m = _registry[1]
        assert m.version == 1
        assert "simplify" in m.description.lower() or "artifact" in m.description.lower()

    def test_drops_search_index(self, db):
        # Create the old search_index table, run migration, verify it's gone
        with db._engine.begin() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS search_index (id serial PRIMARY KEY)"))

        # Reset version so migration will run
        _set_version(db._engine, 0)

        # Drop the new artifacts table so migration can recreate via create_all
        with db._engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS artifacts CASCADE"))

        run_pending(db._engine)
        Base.metadata.create_all(db._engine)

        with db._engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'search_index'")
            ).fetchone()
            assert row is None

    def test_drops_old_artifacts_and_creates_new(self, db):
        # Reset version, drop new artifacts, create old-style artifacts
        _set_version(db._engine, 0)
        with db._engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS artifacts CASCADE"))
            conn.execute(
                text(
                    "CREATE TABLE artifacts ("
                    "  id serial PRIMARY KEY,"
                    "  artifact_type varchar NOT NULL,"
                    "  origin varchar NOT NULL,"
                    "  text varchar NOT NULL"
                    ")"
                )
            )

        run_pending(db._engine)
        Base.metadata.create_all(db._engine)

        # New artifacts table should have section_type, not artifact_type
        with db._engine.connect() as conn:
            has_section_type = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'artifacts' AND column_name = 'section_type'"
                )
            ).fetchone()
            has_artifact_type = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'artifacts' AND column_name = 'artifact_type'"
                )
            ).fetchone()
            assert has_section_type is not None
            assert has_artifact_type is None

    def test_drops_transcript_summary_columns(self, db):
        # Add old columns back, then run migration
        with db._engine.begin() as conn:
            for col in ("title varchar", "summary text", "last_summary_at timestamp"):
                name = col.split()[0]
                exists = conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'transcripts' AND column_name = :col"
                    ),
                    {"col": name},
                ).fetchone()
                if not exists:
                    conn.execute(text(f"ALTER TABLE transcripts ADD COLUMN {col}"))

        _set_version(db._engine, 0)
        run_pending(db._engine)

        with db._engine.connect() as conn:
            for col_name in ("title", "summary", "last_summary_at"):
                row = conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'transcripts' AND column_name = :col"
                    ),
                    {"col": col_name},
                ).fetchone()
                assert row is None, f"Column {col_name} should have been dropped"

    def test_migration_idempotent(self, db):
        """Running migration 001 twice should not error."""
        _set_version(db._engine, 0)
        with db._engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS artifacts CASCADE"))

        run_pending(db._engine)
        Base.metadata.create_all(db._engine)

        # Run again — should be a no-op since version is already set
        applied = run_pending(db._engine)
        assert applied == []


class TestDatabaseInitStamping:
    """Tests for Database.__init__ stamping behavior."""

    def test_new_install_stamped(self, db):
        """A fresh Database() should stamp the version automatically."""
        assert get_current_version(db._engine) == get_latest_version()
        assert not needs_migration(db._engine)
