"""Tests for observer.db module."""

import pytest
from observer.data.schemas import ProjectSchema
from observer.exceptions import DatabaseNotConfiguredError
from observer.services.db import Database
from sqlalchemy import text
from sqlalchemy.orm import Session


class TestSQLiteSetup:
    """Tests for SQLite database setup."""

    def test_wal_mode_enabled(self, db):
        with db.session() as session:
            result = session.execute(text("PRAGMA journal_mode")).scalar()
            assert result == "wal"

    def test_foreign_keys_enabled(self, db):
        with db.session() as session:
            result = session.execute(text("PRAGMA foreign_keys")).scalar()
            assert result == 1

    def test_fts5_table_exists(self, db):
        with db.session() as session:
            result = session.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='artifacts_fts'")
            ).fetchone()
            assert result is not None


class TestDatabaseSession:
    """Tests for Database.session() context manager."""

    def test_yields_session(self, db):
        with db.session() as session:
            assert isinstance(session, Session)

    def test_commits_on_success(self, db):
        with db.session() as session:
            session.add(ProjectSchema(name="commit-test", repo_path="/tmp/commit-test"))

        with db.session() as session:
            result = session.query(ProjectSchema).filter_by(name="commit-test").first()
            assert result is not None

    def test_rolls_back_on_error(self, db):
        with pytest.raises(RuntimeError):
            with db.session() as session:
                session.add(ProjectSchema(name="rollback-inner", repo_path="/tmp/rollback-inner"))
                raise RuntimeError

        with db.session() as session:
            result = session.query(ProjectSchema).filter_by(name="rollback-inner").first()
            assert result is None


class TestDatabaseClose:
    """Tests for Database.close()."""

    def test_can_create_new_instance_after_close(self, db, tmp_path, monkeypatch):  # noqa: ARG002
        db_url = f"sqlite:///{tmp_path / 'test2.db'}"
        db.close()

        Database.configure(db_url)
        db2 = Database()
        with db2.session() as session:
            assert isinstance(session, Session)

        db2.close()


class TestDatabaseMissingUrl:
    """Tests for missing OBSERVER_DB_URL."""

    def test_raises_if_url_missing(self, monkeypatch):
        monkeypatch.setattr(Database, "_instance", None)
        monkeypatch.setattr(Database, "_url", None)
        monkeypatch.delenv("OBSERVER_DB_URL", raising=False)
        monkeypatch.setattr("observer.services.db.DB_URL", "")

        with pytest.raises(DatabaseNotConfiguredError):
            Database()
