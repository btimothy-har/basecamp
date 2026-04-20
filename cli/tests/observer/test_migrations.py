"""Tests for the migration runner."""

from observer.services.migrations import (
    _registry,
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
        with db._engine.begin() as conn:
            conn.execute(text("UPDATE schema_version SET version = 0"))

        applied = run_pending(db._engine)
        assert len(applied) >= 1
        assert get_current_version(db._engine) == get_latest_version()


class TestDatabaseInitStamping:
    """Tests for Database.__init__ stamping behavior."""

    def test_new_install_stamped(self, db):
        """A fresh Database() should stamp the version automatically."""
        assert get_current_version(db._engine) == get_latest_version()
        assert not needs_migration(db._engine)
