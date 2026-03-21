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
from observer.pipeline import indexing
from observer.pipeline.indexing import SearchIndexer, _content_hash


def _mock_model(n: int | None = None):
    """Return a mock SentenceTransformer that produces random embeddings.

    If n is None, dynamically sizes output to match input length.
    """
    model = MagicMock()
    if n is None:
        model.encode.side_effect = lambda texts, **_: np.random.rand(len(texts), EMBEDDING_DIMENSIONS).astype(
            np.float32
        )
    else:
        model.encode.return_value = np.random.rand(n, EMBEDDING_DIMENSIONS).astype(np.float32)
    return model


def _seed_project_and_transcript(db, *, session_id="sess-1"):
    """Create a project and transcript. Returns (project_id, transcript_id)."""
    with db.session() as session:
        project = ProjectSchema(name="test-project", repo_path="/tmp/test")
        session.add(project)
        session.flush()

        transcript = TranscriptSchema(
            project_id=project.id,
            session_id=session_id,
            path=f"/tmp/transcript-{session_id}.jsonl",
        )
        session.add(transcript)
        session.flush()

        return project.id, transcript.id


def _create_artifact(
    db,
    transcript_id,
    *,
    text="some knowledge",
    section_type=SectionType.KNOWLEDGE,
):
    """Create an artifact. Returns artifact ID."""
    with db.session() as session:
        extraction = ArtifactSchema(
            transcript_id=transcript_id,
            section_type=section_type,
            text=text,
        )
        session.add(extraction)
        session.flush()
        return extraction.id


def _mark_indexed(db, ext_id, *, text=None, stale_hash=False):
    """Mark an extraction as already indexed with embedding and hash."""
    embedding = np.random.rand(EMBEDDING_DIMENSIONS).astype(np.float32).tolist()
    with db.session() as session:
        extraction = session.get(ArtifactSchema, ext_id)
        extraction.embedding = embedding
        extraction.content_hash = _content_hash("wrong" if stale_hash else (text or extraction.text))
        extraction.indexed_at = datetime.now(UTC)


class TestHasPending:
    def test_false_when_empty(self, db):  # noqa: ARG002
        assert SearchIndexer.has_pending() is False

    def test_true_when_unindexed_extraction(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        _create_artifact(db, transcript_id)
        assert SearchIndexer.has_pending() is True

    def test_false_when_all_indexed(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        ext_id = _create_artifact(db, transcript_id)
        _mark_indexed(db, ext_id)
        assert SearchIndexer.has_pending() is False

    def test_true_when_summary_unindexed(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        _create_artifact(db, transcript_id, text="A summary.", section_type=SectionType.SUMMARY)
        assert SearchIndexer.has_pending() is True

    def test_true_when_content_changed(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        ext_id = _create_artifact(db, transcript_id, text="Updated text.")
        _mark_indexed(db, ext_id, stale_hash=True)
        assert SearchIndexer.has_pending() is True

    def test_false_when_content_current(self, db):
        text = "Current text."
        _, transcript_id = _seed_project_and_transcript(db)
        ext_id = _create_artifact(db, transcript_id, text=text)
        _mark_indexed(db, ext_id, text=text)
        assert SearchIndexer.has_pending() is False

    def test_true_when_updated_after_indexed(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        ext_id = _create_artifact(db, transcript_id)
        _mark_indexed(db, ext_id)

        # Simulate text update after indexing
        with db.session() as session:
            extraction = session.get(ArtifactSchema, ext_id)
            extraction.updated_at = datetime.now(UTC) + timedelta(seconds=1)

        assert SearchIndexer.has_pending() is True


class TestIndexBatch:
    def test_indexes_extraction(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        ext_id = _create_artifact(db, transcript_id, text="extraction text")

        with patch.object(indexing, "_get_model", return_value=_mock_model(1)):
            count = SearchIndexer.index_batch(db)

        assert count == 1

        with db.session() as session:
            extraction = session.get(ArtifactSchema, ext_id)
            assert extraction.embedding is not None
            assert len(extraction.embedding) == EMBEDDING_DIMENSIONS
            assert extraction.content_hash == _content_hash("extraction text")
            assert extraction.indexed_at is not None

    def test_returns_zero_when_nothing_pending(self, db):  # noqa: ARG002
        with patch.object(indexing, "_get_model") as mock_st_cls:
            count = SearchIndexer.index_batch(db)

        assert count == 0
        mock_st_cls.assert_not_called()

    def test_respects_batch_limit(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        for i in range(5):
            _create_artifact(db, transcript_id, text=f"extraction {i}", section_type=list(SectionType)[i])

        with patch.object(indexing, "_get_model", return_value=_mock_model(2)):
            count = SearchIndexer.index_batch(db, batch_limit=2)

        assert count == 2

        with db.session() as session:
            indexed = (
                session.query(ArtifactSchema)
                .filter(ArtifactSchema.embedding.isnot(None))
                .count()
            )
            assert indexed == 2

    def test_indexes_summary_section(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        ext_id = _create_artifact(
            db, transcript_id, text="Session summary text.", section_type=SectionType.SUMMARY
        )

        with patch.object(indexing, "_get_model", return_value=_mock_model(1)):
            count = SearchIndexer.index_batch(db)

        assert count == 1

        with db.session() as session:
            extraction = session.get(ArtifactSchema, ext_id)
            assert extraction.embedding is not None
            assert extraction.content_hash == _content_hash("Session summary text.")

    def test_updates_changed_content(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        ext_id = _create_artifact(db, transcript_id, text="New text.")
        _mark_indexed(db, ext_id, stale_hash=True)

        with patch.object(indexing, "_get_model", return_value=_mock_model(1)):
            count = SearchIndexer.index_batch(db)

        assert count == 1

        with db.session() as session:
            extraction = session.get(ArtifactSchema, ext_id)
            assert extraction.content_hash == _content_hash("New text.")

    def test_skips_unchanged_content(self, db):
        text = "Unchanged text."
        _, transcript_id = _seed_project_and_transcript(db)
        ext_id = _create_artifact(db, transcript_id, text=text)
        _mark_indexed(db, ext_id, text=text)

        with patch.object(indexing, "_get_model") as mock_st_cls:
            count = SearchIndexer.index_batch(db)

        assert count == 0
        mock_st_cls.assert_not_called()

    def test_indexes_multiple_sections_in_one_batch(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        _create_artifact(db, transcript_id, text="A summary.", section_type=SectionType.SUMMARY)
        _create_artifact(db, transcript_id, text="A decision.", section_type=SectionType.DECISIONS)

        with patch.object(indexing, "_get_model", return_value=_mock_model()):
            count = SearchIndexer.index_batch(db)

        assert count == 2

        with db.session() as session:
            indexed = (
                session.query(ArtifactSchema)
                .filter(ArtifactSchema.embedding.isnot(None))
                .count()
            )
            assert indexed == 2
