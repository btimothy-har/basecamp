"""Tests for observer.mcp.engine module."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import numpy as np
from observer.constants import EMBEDDING_DIMENSIONS
from observer.data.enums import SectionType
from observer.data.schemas import (
    ArtifactSchema,
    ProjectSchema,
    TranscriptSchema,
)
from observer.mcp import engine


def _random_embedding() -> list[float]:
    return np.random.rand(EMBEDDING_DIMENSIONS).astype(np.float32).tolist()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _mock_model():
    model = MagicMock()
    model.encode.return_value = np.random.rand(1, EMBEDDING_DIMENSIONS).astype(np.float32)
    return model


def _seed_artifact(
    db,
    *,
    section_type=SectionType.KNOWLEDGE,
    session_id="sess-1",
    project_name="test-project",
    embedding=None,
):
    """Create a project, transcript, and indexed extraction. Returns extraction ID."""
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
        extraction = ArtifactSchema(
            transcript_id=transcript.id,
            section_type=section_type,
            text=text,
            embedding=embedding if embedding is not None else _random_embedding(),
            content_hash=_content_hash(text),
            indexed_at=datetime.now(UTC),
        )
        session.add(extraction)
        session.flush()

        return extraction.id


def _seed_summary(
    db,
    *,
    session_id="sess-summary",
    summary_text="## Test Title\nTest transcript summary",
    project_name="test-project",
):
    """Create a project, transcript, and indexed summary extraction. Returns transcript ID."""
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

        extraction = ArtifactSchema(
            transcript_id=transcript.id,
            section_type=SectionType.SUMMARY,
            text=summary_text,
            embedding=_random_embedding(),
            content_hash=_content_hash(summary_text),
            indexed_at=datetime.now(UTC),
        )
        session.add(extraction)
        session.flush()

        return transcript.id


class TestSearchArtifacts:
    def test_returns_extraction_results(self, db):  # noqa: ARG002
        _seed_artifact(db)

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project")

        assert len(results) >= 1
        result = results[0]
        assert "session_id" in result
        assert "text" in result
        assert "score" in result
        assert "type" in result

    def test_excludes_summaries(self, db):  # noqa: ARG002
        _seed_summary(db, session_id="sess-excluded")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project")

        for r in results:
            assert r.get("type") != SectionType.SUMMARY

    def test_scopes_to_project(self, db):  # noqa: ARG002
        _seed_artifact(db, session_id="sess-scoped")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "nonexistent-project")

        assert len(results) == 0

    def test_respects_top_k(self, db):  # noqa: ARG002
        for i in range(5):
            _seed_artifact(db, session_id=f"sess-topk-{i}")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project", top_k=2)

        assert len(results) <= 2

    def test_threshold_filters_low_scores(self, db):  # noqa: ARG002
        _seed_artifact(db, session_id="sess-thresh")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project", threshold=0.99)

        for r in results:
            assert r["score"] >= 0.99

    def test_none_project_returns_all_projects(self, db):  # noqa: ARG002
        _seed_artifact(db, session_id="sess-proj-a", project_name="project-a")
        _seed_artifact(db, session_id="sess-proj-b", project_name="project-b")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", None, top_k=50, threshold=0.0)

        assert len(results) >= 2

    def test_empty_db_returns_empty(self, db):  # noqa: ARG002
        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project")

        assert results == []

    def test_excludes_current_session(self, db):  # noqa: ARG002
        _seed_artifact(db, session_id="current-session")
        _seed_artifact(db, session_id="other-session")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project", threshold=0.0, session_id="current-session")

        for r in results:
            assert r["session_id"] != "current-session"

    def test_section_types_filters_at_query_level(self, db):  # noqa: ARG002
        """section_types restricts results before LIMIT, not after.

        Without pre-query filtering the DECISIONS row would rank first
        (its embedding is identical to the query vector) and claim the
        single top_k=1 slot, leaving zero KNOWLEDGE results after a
        hypothetical post-trim filter.  The assertion that we get
        exactly one KNOWLEDGE result proves the filter runs in SQL.
        """
        # Unit vector along dim 0 — used as both query and DECISIONS embedding.
        close_vec = np.zeros(EMBEDDING_DIMENSIONS, dtype=np.float32)
        close_vec[0] = 1.0
        # Orthogonal vector — KNOWLEDGE embedding, high cosine distance.
        far_vec = np.zeros(EMBEDDING_DIMENSIONS, dtype=np.float32)
        far_vec[1] = 1.0

        _seed_artifact(
            db,
            section_type=SectionType.DECISIONS,
            session_id="sess-type-d",
            embedding=close_vec.tolist(),
        )
        _seed_artifact(
            db,
            section_type=SectionType.KNOWLEDGE,
            session_id="sess-type-k",
            embedding=far_vec.tolist(),
        )

        model = MagicMock()
        model.encode.return_value = close_vec.reshape(1, -1)

        with patch.object(engine, "_get_model", return_value=model):
            results = engine.search_artifacts(
                "test query",
                "test-project",
                top_k=1,
                threshold=0.0,
                section_types=["knowledge"],
            )

        assert len(results) == 1
        assert results[0]["type"] == SectionType.KNOWLEDGE

    def test_excludes_unindexed_extractions(self, db):  # noqa: ARG002
        """Extractions without embeddings should not appear in search results."""
        with db.session() as session:
            project = ProjectSchema(name="test-project", repo_path="/tmp/test-project")
            session.add(project)
            session.flush()

            transcript = TranscriptSchema(
                project_id=project.id,
                session_id="sess-unindexed",
                path="/tmp/transcript-unindexed.jsonl",
            )
            session.add(transcript)
            session.flush()

            # Extraction without embedding (not yet indexed)
            extraction = ArtifactSchema(
                transcript_id=transcript.id,
                section_type=SectionType.KNOWLEDGE,
                text="unindexed knowledge",
            )
            session.add(extraction)

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
        assert "session_id" in result
        assert "text" in result
        assert "score" in result
        assert "title" in result

    def test_excludes_non_summary_sections(self, db):  # noqa: ARG002
        _seed_artifact(db, session_id="sess-excluded")

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

    def test_excludes_current_session(self, db):  # noqa: ARG002
        _seed_summary(db, session_id="current-session-ts", summary_text="## Current\nCurrent summary")
        _seed_summary(db, session_id="other-session-ts", summary_text="## Other\nOther summary")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts(
                "test query", "test-project", threshold=0.0, session_id="current-session-ts"
            )

        for r in results:
            assert r["session_id"] != "current-session-ts"

    def test_empty_db_returns_empty(self, db):  # noqa: ARG002
        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts("test query", "test-project")

        assert results == []


class TestGetSession:
    def test_returns_session_with_sections(self, db):
        """Found session returns session_id, timestamps, and all extraction sections."""
        transcript_id = _seed_summary(db, session_id="sess-get-session")

        # Add a second section type to the same transcript
        with db.session() as session:
            extraction = ArtifactSchema(
                transcript_id=transcript_id,
                section_type=SectionType.KNOWLEDGE,
                text="some knowledge",
            )
            session.add(extraction)

        result = engine.get_session("sess-get-session")

        assert result is not None
        assert result["session_id"] == "sess-get-session"
        assert "started_at" in result
        assert "ended_at" in result
        assert "sections" in result
        assert SectionType.SUMMARY in result["sections"]
        assert SectionType.KNOWLEDGE in result["sections"]

    def test_returns_none_for_missing(self, db):  # noqa: ARG002
        result = engine.get_session("nonexistent-session")
        assert result is None
