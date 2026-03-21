"""Tests for observer.db module."""

import pytest
from observer.data.schemas import ProjectSchema
from observer.exceptions import DatabaseNotConfiguredError
from observer.services.db import Base, Database
from sqlalchemy import text
from sqlalchemy.orm import Session


class TestPgvector:
    """Tests for pgvector extension and schema setup."""

    def test_vector_extension_installed(self, db):
        with db.session() as session:
            result = session.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'")).scalar()
            assert result == "vector"


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

    def test_can_create_new_instance_after_close(self, pg_url):
        Database.configure(pg_url)
        db1 = Database()
        db1.close()

        Database.configure(pg_url)
        db2 = Database()
        with db2.session() as session:
            assert isinstance(session, Session)

        Base.metadata.drop_all(db2._engine)
        db2.close()


class TestDatabaseMissingUrl:
    """Tests for missing OBSERVER_PG_URL."""

    def test_raises_if_url_missing(self, monkeypatch):
        monkeypatch.setattr(Database, "_instance", None)
        monkeypatch.setattr(Database, "_url", None)
        monkeypatch.delenv("OBSERVER_PG_URL", raising=False)
        monkeypatch.setattr("observer.services.db.get_pg_url", lambda: None)

        with pytest.raises(DatabaseNotConfiguredError, match="OBSERVER_PG_URL is not configured"):
            Database()


class TestExtractionEmbedding:
    """Tests for embedding support on artifacts table."""

    def test_hnsw_index_exists(self, db):
        with db.session() as session:
            result = session.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'artifacts' "
                    "AND indexname = 'ix_artifacts_embedding_hnsw'"
                )
            ).scalar()
            assert result == "ix_artifacts_embedding_hnsw"

    def test_embedding_column_dimensions(self, db):
        with db.session() as session:
            result = session.execute(
                text(
                    "SELECT atttypmod FROM pg_attribute "
                    "JOIN pg_class ON pg_attribute.attrelid = pg_class.oid "
                    "WHERE pg_class.relname = 'artifacts' "
                    "AND pg_attribute.attname = 'embedding'"
                )
            ).scalar()
            assert result == 384
