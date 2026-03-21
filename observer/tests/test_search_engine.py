"""Tests for observer.mcp.engine module."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import numpy as np
from observer.constants import EMBEDDING_DIMENSIONS
from observer.data.enums import SectionType
from observer.data.schemas import (
    ProjectSchema,
    SearchIndexSchema,
    TranscriptExtractionSchema,
    TranscriptSchema,
)
from observer.mcp import engine


def _random_embedding() -> list[float]:
    return np.random.rand(EMBEDDING_DIMENSIONS).astype(np.float32).tolist()


def _fixed_embedding(base: float = 1.0, offset: int = 0) -> list[float]:
    """Deterministic embedding with energy at a specific offset.

    Embeddings with the same offset have cosine similarity 1.0; different
    offsets are orthogonal. Adding a small base keeps vectors non-sparse
    so they have high mutual similarity when offsets are close.
    """
    values = [0.1] * EMBEDDING_DIMENSIONS
    values[offset % EMBEDDING_DIMENSIONS] = base
    return values


def _mock_model():
    model = MagicMock()
    model.encode.return_value = np.random.rand(1, EMBEDDING_DIMENSIONS).astype(np.float32)
    return model


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _seed_extraction(
    db,
    *,
    section_type=SectionType.KNOWLEDGE,
    session_id="sess-1",
    project_name="test-project",
):
    """Create a project, transcript, extraction, and search_index entry. Returns extraction ID."""
    with db.session() as session:
        project = session.query(ProjectSchema).filter(ProjectSchema.name == project_name).first()
        if project is None:
            project = ProjectSchema(name=project_name, repo_path=f"/tmp/{project_name}")
            session.add(project)
            session.flush()

        transcript = TranscriptSchema(
            project_id=project.id,
            session_id=session_id,
            path=f"/tmp/transcript-{session_id}.jsonl",
        )
        session.add(transcript)
        session.flush()

        text = f"test extraction of type {section_type.value}"
        extraction = TranscriptExtractionSchema(
            transcript_id=transcript.id,
            section_type=section_type,
            text=text,
        )
        session.add(extraction)
        session.flush()

        index_entry = SearchIndexSchema(
            section_type=section_type,
            source_id=extraction.id,
            project_id=project.id,
            transcript_id=transcript.id,
            text=text,
            content_hash=_content_hash(text),
            embedding=_random_embedding(),
            created_at=datetime.now(UTC),
        )
        session.add(index_entry)
        session.flush()

        return extraction.id


def _seed_summary(
    db,
    *,
    session_id="sess-summary",
    summary_text="## Test Title\nTest transcript summary",
    project_name="test-project",
):
    """Create a project, transcript, summary extraction, and search_index entry. Returns transcript ID."""
    with db.session() as session:
        project = session.query(ProjectSchema).filter(ProjectSchema.name == project_name).first()
        if project is None:
            project = ProjectSchema(name=project_name, repo_path=f"/tmp/{project_name}")
            session.add(project)
            session.flush()

        transcript = TranscriptSchema(
            project_id=project.id,
            session_id=session_id,
            path=f"/tmp/transcript-{session_id}.jsonl",
        )
        session.add(transcript)
        session.flush()

        extraction = TranscriptExtractionSchema(
            transcript_id=transcript.id,
            section_type=SectionType.SUMMARY,
            text=summary_text,
        )
        session.add(extraction)
        session.flush()

        index_entry = SearchIndexSchema(
            section_type=SectionType.SUMMARY,
            source_id=extraction.id,
            project_id=project.id,
            transcript_id=transcript.id,
            text=summary_text,
            content_hash=_content_hash(summary_text),
            embedding=_random_embedding(),
            created_at=datetime.now(UTC),
        )
        session.add(index_entry)
        session.flush()

        return transcript.id


class TestSearchArtifacts:
    def test_returns_extraction_results(self, db):  # noqa: ARG002
        _seed_extraction(db)

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project")

        assert len(results) >= 1
        result = results[0]
        assert "source_id" in result
        assert "text" in result
        assert "score" in result
        assert "transcript_id" in result
        assert "type" in result

    def test_excludes_summaries(self, db):  # noqa: ARG002
        _seed_summary(db, session_id="sess-excluded")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project")

        # Summary sections should not appear in artifact search
        for r in results:
            assert r.get("type") != SectionType.SUMMARY

    def test_scopes_to_project(self, db):  # noqa: ARG002
        _seed_extraction(db, session_id="sess-scoped")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "nonexistent-project")

        assert len(results) == 0

    def test_excludes_current_session(self, db):  # noqa: ARG002
        _seed_extraction(db, session_id="current-session")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project", session_id="current-session")

        assert len(results) == 0

    def test_respects_top_k(self, db):  # noqa: ARG002
        for i in range(5):
            _seed_extraction(db, session_id=f"sess-topk-{i}")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project", top_k=2)

        assert len(results) <= 2

    def test_threshold_filters_low_scores(self, db):  # noqa: ARG002
        _seed_extraction(db, session_id="sess-thresh")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project", threshold=0.99)

        for r in results:
            assert r["score"] >= 0.99

    def test_none_project_returns_all_projects(self, db):  # noqa: ARG002
        _seed_extraction(db, session_id="sess-proj-a", project_name="project-a")
        _seed_extraction(db, session_id="sess-proj-b", project_name="project-b")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", None, top_k=50, threshold=0.0)

        assert len(results) >= 2

    def test_empty_db_returns_empty(self, db):  # noqa: ARG002
        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project")

        assert results == []


class TestSearchTranscripts:
    def test_returns_transcript_results(self, db):  # noqa: ARG002
        _seed_summary(db)

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts("test query", "test-project")

        assert len(results) >= 1
        result = results[0]
        assert "source_id" in result
        assert "text" in result
        assert "score" in result
        assert "title" in result
        assert "transcript_id" in result

    def test_excludes_non_summary_sections(self, db):  # noqa: ARG002
        _seed_extraction(db, session_id="sess-excluded")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts("test query", "test-project")

        # Non-summary extraction results should not appear in transcript search
        for r in results:
            assert "type" not in r

    def test_scopes_to_project(self, db):  # noqa: ARG002
        _seed_summary(db, session_id="sess-scoped-ts")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts("test query", "nonexistent-project")

        assert len(results) == 0

    def test_excludes_current_session(self, db):  # noqa: ARG002
        _seed_summary(db, session_id="current-session-ts")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts("test query", "test-project", session_id="current-session-ts")

        assert len(results) == 0

    def test_respects_top_k(self, db):  # noqa: ARG002
        for i in range(5):
            _seed_summary(db, session_id=f"sess-topk-ts-{i}", summary_text=f"## Title {i}\nSummary {i}")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts("test query", "test-project", top_k=2)

        assert len(results) <= 2

    def test_none_project_returns_all_projects(self, db):  # noqa: ARG002
        _seed_summary(db, session_id="sess-ts-a", summary_text="## A\nSummary A", project_name="project-a")
        _seed_summary(db, session_id="sess-ts-b", summary_text="## B\nSummary B", project_name="project-b")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts("test query", None, top_k=50, threshold=0.0)

        assert len(results) >= 2

    def test_empty_db_returns_empty(self, db):  # noqa: ARG002
        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts("test query", "test-project")

        assert results == []


class TestGetExtraction:
    def test_returns_extraction(self, db):  # noqa: ARG002
        ext_id = _seed_extraction(db, session_id="sess-get")

        result = engine.get_extraction(ext_id)

        assert result is not None
        assert result["id"] == ext_id
        assert result["section_type"] == SectionType.KNOWLEDGE
        assert "text" in result

    def test_returns_none_for_missing(self, db):  # noqa: ARG002
        result = engine.get_extraction(99999)
        assert result is None


class TestGetTranscriptSummary:
    def test_returns_summary(self, db):  # noqa: ARG002
        transcript_id = _seed_summary(db, session_id="sess-get-summary")

        result = engine.get_transcript_summary(transcript_id)

        assert result is not None
        assert result["id"] == transcript_id
        assert result["title"] == "Test Title"
        assert result["session_id"] == "sess-get-summary"
        assert "started_at" in result
        assert "sections" in result

    def test_returns_none_for_missing(self, db):  # noqa: ARG002
        result = engine.get_transcript_summary(99999)
        assert result is None
