"""Tests for observer.db module."""

from datetime import UTC, datetime

import pytest
from observer.data.enums import SectionType
from observer.data.schemas import ProjectSchema, SearchIndexSchema
from observer.exceptions import DatabaseNotConfiguredError
from observer.services.db import Base, Database
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
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


class TestSearchIndex:
    """Tests for search_index table schema."""

    def test_table_created(self, db):
        with db.session() as session:
            result = session.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_name = 'search_index'")
            ).scalar()
            assert result == "search_index"

    def test_unique_constraint(self, db):
        with db.session() as session:
            project = ProjectSchema(name="si-proj", repo_path="/tmp/si")
            session.add(project)
            session.flush()
            project_id = project.id

            entry = SearchIndexSchema(
                section_type=SectionType.KNOWLEDGE,
                source_id=1,
                project_id=project_id,
                text="first entry",
                content_hash="abc123",
                created_at=datetime.now(UTC),
            )
            session.add(entry)
            session.flush()

        with pytest.raises(IntegrityError):
            with db.session() as session:
                duplicate = SearchIndexSchema(
                    section_type=SectionType.KNOWLEDGE,
                    source_id=1,
                    project_id=project_id,
                    text="duplicate entry",
                    content_hash="def456",
                    created_at=datetime.now(UTC),
                )
                session.add(duplicate)

    def test_hnsw_index_exists(self, db):
        with db.session() as session:
            result = session.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'search_index' "
                    "AND indexname = 'ix_search_index_embedding_hnsw'"
                )
            ).scalar()
            assert result == "ix_search_index_embedding_hnsw"

    def test_embedding_column_dimensions(self, db):
        with db.session() as session:
            result = session.execute(
                text(
                    "SELECT atttypmod FROM pg_attribute "
                    "JOIN pg_class ON pg_attribute.attrelid = pg_class.oid "
                    "WHERE pg_class.relname = 'search_index' "
                    "AND pg_attribute.attname = 'embedding'"
                )
            ).scalar()
            assert result == 384
