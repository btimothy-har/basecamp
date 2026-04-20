"""Tests for observer.pipeline.indexing module."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
from observer.constants import EMBEDDING_DIMENSIONS
from observer.data.enums import SectionType
from observer.data.schemas import (
    ArtifactSchema,
    ProjectSchema,
    TranscriptSchema,
)
from observer.pipeline.indexing import SearchIndexer, _content_hash


def _mock_encode(n: int | None = None):
    """Return a mock chroma.encode that produces random embeddings.

    If n is None, dynamically sizes output to match input length.
    """
    if n is None:
        return lambda texts: np.random.rand(len(texts), EMBEDDING_DIMENSIONS).astype(np.float32).tolist()
    return lambda _texts: np.random.rand(n, EMBEDDING_DIMENSIONS).astype(np.float32).tolist()


def _mock_collection():
    """Return a mock ChromaDB collection."""
    collection = MagicMock()
    collection.upsert = MagicMock()
    return collection


def _seed_project_and_transcript(db, *, session_id="sess-1"):
    with db.session() as session:
        project = ProjectSchema(name="test-project", repo_path="/tmp/test-project")
        session.add(project)
        session.flush()

        transcript = TranscriptSchema(
            project_id=project.id,
            session_id=session_id,
            path="/tmp/test.jsonl",
        )
        session.add(transcript)
        session.flush()
        return project.id, transcript.id


def _create_artifact(db, transcript_id, *, text="test text", section_type=SectionType.KNOWLEDGE):
    with db.session() as session:
        now = datetime.now(UTC)
        ext = ArtifactSchema(
            transcript_id=transcript_id,
            section_type=section_type,
            text=text,
            created_at=now,
            updated_at=now,
        )
        session.add(ext)
        session.flush()
        return ext.id


def _mark_indexed(db, artifact_id, *, text=None):
    """Mark an artifact as already indexed."""
    with db.session() as session:
        ext = session.get(ArtifactSchema, artifact_id)
        ext.indexed_at = datetime.now(UTC)
        if text is not None:
            ext.content_hash = _content_hash(text)
        else:
            ext.content_hash = "old-hash"


class TestContentHash:
    def test_deterministic(self):
        assert _content_hash("hello") == _content_hash("hello")

    def test_different_text_different_hash(self):
        assert _content_hash("hello") != _content_hash("world")


class TestHasPending:
    def test_no_artifacts_returns_false(self, db):  # noqa: ARG002
        assert SearchIndexer.has_pending() is False

    def test_unindexed_artifact_returns_true(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        _create_artifact(db, transcript_id)
        assert SearchIndexer.has_pending() is True

    def test_indexed_unchanged_returns_false(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        ext_id = _create_artifact(db, transcript_id, text="hello")
        _mark_indexed(db, ext_id, text="hello")
        assert SearchIndexer.has_pending() is False

    def test_indexed_but_updated_returns_true(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        ext_id = _create_artifact(db, transcript_id)
        _mark_indexed(db, ext_id)

        with db.session() as session:
            ext = session.get(ArtifactSchema, ext_id)
            ext.updated_at = datetime.now(UTC) + timedelta(seconds=1)

        assert SearchIndexer.has_pending() is True


class TestIndexPending:
    def test_indexes_extraction(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        ext_id = _create_artifact(db, transcript_id, text="extraction text")

        with (
            patch("observer.pipeline.indexing.chroma") as mock_chroma,
        ):
            mock_chroma.encode = _mock_encode(1)
            mock_chroma.get_collection.return_value = _mock_collection()
            count = SearchIndexer.index_pending(db)

        assert count == 1

        with db.session() as session:
            extraction = session.get(ArtifactSchema, ext_id)
            assert extraction.content_hash == _content_hash("extraction text")
            assert extraction.indexed_at is not None

    def test_returns_zero_when_nothing_pending(self, db):  # noqa: ARG002
        count = SearchIndexer.index_pending(db)
        assert count == 0

    def test_indexes_summary_section(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        ext_id = _create_artifact(db, transcript_id, text="Session summary text.", section_type=SectionType.SUMMARY)

        with (
            patch("observer.pipeline.indexing.chroma") as mock_chroma,
        ):
            mock_chroma.encode = _mock_encode(1)
            mock_chroma.get_collection.return_value = _mock_collection()
            count = SearchIndexer.index_pending(db)

        assert count == 1

        with db.session() as session:
            extraction = session.get(ArtifactSchema, ext_id)
            assert extraction.content_hash == _content_hash("Session summary text.")

    def test_reindexes_when_updated_after_indexed(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        ext_id = _create_artifact(db, transcript_id, text="New text.")
        _mark_indexed(db, ext_id)

        # Simulate text update after indexing
        with db.session() as session:
            extraction = session.get(ArtifactSchema, ext_id)
            extraction.updated_at = datetime.now(UTC) + timedelta(seconds=1)

        with (
            patch("observer.pipeline.indexing.chroma") as mock_chroma,
        ):
            mock_chroma.encode = _mock_encode(1)
            mock_chroma.get_collection.return_value = _mock_collection()
            count = SearchIndexer.index_pending(db)

        assert count == 1

        with db.session() as session:
            extraction = session.get(ArtifactSchema, ext_id)
            assert extraction.content_hash == _content_hash("New text.")

    def test_skips_unchanged_content(self, db):
        text = "Unchanged text."
        _, transcript_id = _seed_project_and_transcript(db)
        ext_id = _create_artifact(db, transcript_id, text=text)
        _mark_indexed(db, ext_id, text=text)

        count = SearchIndexer.index_pending(db)
        assert count == 0

    def test_indexes_multiple_sections_in_one_batch(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        _create_artifact(db, transcript_id, text="A summary.", section_type=SectionType.SUMMARY)
        _create_artifact(db, transcript_id, text="A decision.", section_type=SectionType.DECISIONS)

        with (
            patch("observer.pipeline.indexing.chroma") as mock_chroma,
        ):
            mock_chroma.encode = _mock_encode()
            mock_chroma.get_collection.return_value = _mock_collection()
            count = SearchIndexer.index_pending(db)

        assert count == 2

        with db.session() as session:
            indexed = session.query(ArtifactSchema).filter(ArtifactSchema.indexed_at.isnot(None)).count()
            assert indexed == 2
