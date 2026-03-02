"""Tests for observer.pipeline.indexing module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import numpy as np
from observer.constants import EMBEDDING_DIMENSIONS
from observer.data.enums import ArtifactSource, ArtifactType, SearchSourceType
from observer.data.schemas import (
    ArtifactSchema,
    ProjectSchema,
    SearchIndexSchema,
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


def _seed_project_and_transcript(db, *, session_id="sess-1", summary=None):
    """Create a project and transcript. Returns (project_id, transcript_id)."""
    with db.session() as session:
        project = ProjectSchema(name="test-project", repo_path="/tmp/test")
        session.add(project)
        session.flush()

        transcript = TranscriptSchema(
            project_id=project.id,
            session_id=session_id,
            path=f"/tmp/transcript-{session_id}.jsonl",
            summary=summary,
        )
        session.add(transcript)
        session.flush()

        return project.id, transcript.id


def _create_artifact(db, transcript_id, *, text="some knowledge", artifact_type=ArtifactType.KNOWLEDGE):
    """Create an artifact linked to a transcript. Returns artifact ID."""
    with db.session() as session:
        artifact = ArtifactSchema(
            artifact_type=artifact_type.value,
            origin=ArtifactSource.EXTRACTED.value,
            text=text,
            transcript_id=transcript_id,
        )
        session.add(artifact)
        session.flush()
        return artifact.id


class TestHasPending:
    def test_false_when_empty(self, db):  # noqa: ARG002
        assert SearchIndexer.has_pending() is False

    def test_true_when_unindexed_artifact(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        _create_artifact(db, transcript_id)
        assert SearchIndexer.has_pending() is True

    def test_false_when_all_indexed(self, db):
        project_id, transcript_id = _seed_project_and_transcript(db)
        artifact_id = _create_artifact(db, transcript_id)

        with db.session() as session:
            session.add(
                SearchIndexSchema(
                    source_type=SearchSourceType.ARTIFACT.value,
                    source_id=artifact_id,
                    project_id=project_id,
                    transcript_id=transcript_id,
                    text="some knowledge",
                    content_hash=_content_hash("some knowledge"),
                    created_at=datetime.now(UTC),
                )
            )

        assert SearchIndexer.has_pending() is False

    def test_true_when_transcript_summary_unindexed(self, db):
        _seed_project_and_transcript(db, summary="A summary of the session.")
        assert SearchIndexer.has_pending() is True

    def test_true_when_transcript_summary_changed(self, db):
        project_id, transcript_id = _seed_project_and_transcript(db, summary="Updated summary.")

        with db.session() as session:
            session.add(
                SearchIndexSchema(
                    source_type=SearchSourceType.TRANSCRIPT_SUMMARY.value,
                    source_id=transcript_id,
                    project_id=project_id,
                    text="Old summary.",
                    content_hash=_content_hash("Old summary."),
                    created_at=datetime.now(UTC),
                )
            )

        assert SearchIndexer.has_pending() is True

    def test_false_when_transcript_summary_current(self, db):
        summary_text = "Current summary."
        project_id, transcript_id = _seed_project_and_transcript(db, summary=summary_text)

        with db.session() as session:
            session.add(
                SearchIndexSchema(
                    source_type=SearchSourceType.TRANSCRIPT_SUMMARY.value,
                    source_id=transcript_id,
                    project_id=project_id,
                    text=summary_text,
                    content_hash=_content_hash(summary_text),
                    created_at=datetime.now(UTC),
                )
            )

        assert SearchIndexer.has_pending() is False


class TestIndexBatch:
    def test_indexes_artifacts(self, db):
        project_id, transcript_id = _seed_project_and_transcript(db)
        artifact_id = _create_artifact(db, transcript_id, text="artifact text")

        with patch.object(indexing, "_get_model", return_value=_mock_model(1)):
            count = SearchIndexer.index_batch(db)

        assert count == 1

        with db.session() as session:
            entry = (
                session.query(SearchIndexSchema)
                .filter(
                    SearchIndexSchema.source_type == SearchSourceType.ARTIFACT.value,
                    SearchIndexSchema.source_id == artifact_id,
                )
                .one()
            )
            assert entry.project_id == project_id
            assert entry.transcript_id == transcript_id
            assert entry.text == "artifact text"
            assert entry.content_hash == _content_hash("artifact text")
            assert entry.embedding is not None
            assert len(entry.embedding) == EMBEDDING_DIMENSIONS

    def test_excludes_prompt_artifacts(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        _create_artifact(db, transcript_id, artifact_type=ArtifactType.PROMPT)

        with patch.object(indexing, "_get_model") as mock_st_cls:
            count = SearchIndexer.index_batch(db)

        assert count == 0
        mock_st_cls.assert_not_called()

    def test_returns_zero_when_nothing_pending(self, db):  # noqa: ARG002
        with patch.object(indexing, "_get_model") as mock_st_cls:
            count = SearchIndexer.index_batch(db)

        assert count == 0
        mock_st_cls.assert_not_called()

    def test_respects_batch_limit(self, db):
        _, transcript_id = _seed_project_and_transcript(db)
        for i in range(5):
            _create_artifact(db, transcript_id, text=f"artifact {i}")

        with patch.object(indexing, "_get_model", return_value=_mock_model(2)):
            count = SearchIndexer.index_batch(db, batch_limit=2)

        assert count == 2

        with db.session() as session:
            indexed = (
                session.query(SearchIndexSchema)
                .filter(SearchIndexSchema.source_type == SearchSourceType.ARTIFACT.value)
                .count()
            )
            assert indexed == 2

    def test_indexes_transcript_summaries(self, db):
        project_id, transcript_id = _seed_project_and_transcript(db, summary="Session summary text.")

        with patch.object(indexing, "_get_model", return_value=_mock_model(1)):
            count = SearchIndexer.index_batch(db)

        assert count == 1

        with db.session() as session:
            entry = (
                session.query(SearchIndexSchema)
                .filter(
                    SearchIndexSchema.source_type == SearchSourceType.TRANSCRIPT_SUMMARY.value,
                    SearchIndexSchema.source_id == transcript_id,
                )
                .one()
            )
            assert entry.project_id == project_id
            assert entry.text == "Session summary text."
            assert entry.content_hash == _content_hash("Session summary text.")
            assert entry.embedding is not None

    def test_updates_changed_transcript_summary(self, db):
        project_id, transcript_id = _seed_project_and_transcript(
            db,
            summary="New summary.",
        )

        # Seed an existing index entry with the old summary
        with db.session() as session:
            session.add(
                SearchIndexSchema(
                    source_type=SearchSourceType.TRANSCRIPT_SUMMARY.value,
                    source_id=transcript_id,
                    project_id=project_id,
                    text="Old summary.",
                    content_hash=_content_hash("Old summary."),
                    created_at=datetime.now(UTC),
                )
            )

        with patch.object(indexing, "_get_model", return_value=_mock_model(1)):
            count = SearchIndexer.index_batch(db)

        assert count == 1

        with db.session() as session:
            entry = (
                session.query(SearchIndexSchema)
                .filter(
                    SearchIndexSchema.source_type == SearchSourceType.TRANSCRIPT_SUMMARY.value,
                    SearchIndexSchema.source_id == transcript_id,
                )
                .one()
            )
            assert entry.text == "New summary."
            assert entry.content_hash == _content_hash("New summary.")

    def test_skips_unchanged_transcript_summary(self, db):
        summary_text = "Unchanged summary."
        project_id, transcript_id = _seed_project_and_transcript(db, summary=summary_text)

        with db.session() as session:
            session.add(
                SearchIndexSchema(
                    source_type=SearchSourceType.TRANSCRIPT_SUMMARY.value,
                    source_id=transcript_id,
                    project_id=project_id,
                    text=summary_text,
                    content_hash=_content_hash(summary_text),
                    created_at=datetime.now(UTC),
                )
            )

        with patch.object(indexing, "_get_model") as mock_st_cls:
            count = SearchIndexer.index_batch(db)

        assert count == 0
        mock_st_cls.assert_not_called()

    def test_indexes_both_sources_in_one_batch(self, db):
        _, transcript_id = _seed_project_and_transcript(db, summary="A summary.")
        _create_artifact(db, transcript_id, text="an artifact")

        with patch.object(indexing, "_get_model", return_value=_mock_model()):
            count = SearchIndexer.index_batch(db)

        # 1 artifact + 1 transcript summary = 2
        assert count == 2

        with db.session() as session:
            total = session.query(SearchIndexSchema).count()
            assert total == 2
