"""Tests for observer.mcp.engine module."""

from __future__ import annotations

import hashlib
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


def _seed_data(db, *, artifact_type=ArtifactType.KNOWLEDGE, session_id="sess-1"):
    """Create a project, transcript, artifact, and search_index entry. Returns artifact ID.

    Reuses an existing project if one with name 'test-project' already exists.
    """
    with db.session() as session:
        project = session.query(ProjectSchema).filter(ProjectSchema.name == "test-project").first()
        if project is None:
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

        text = f"test artifact of type {artifact_type.value}"
        artifact = ArtifactSchema(
            artifact_type=artifact_type.value,
            origin=ArtifactSource.EXTRACTED.value,
            text=text,
            transcript_id=transcript.id,
            created_at=datetime.now(UTC),
        )
        session.add(artifact)
        session.flush()

        # Only index non-PROMPT artifacts (mirrors SearchIndexer behavior)
        if artifact_type != ArtifactType.PROMPT:
            index_entry = SearchIndexSchema(
                source_type=SearchSourceType.ARTIFACT.value,
                source_id=artifact.id,
                project_id=project.id,
                transcript_id=transcript.id,
                text=text,
                content_hash=_content_hash(text),
                embedding=_random_embedding(),
                created_at=datetime.now(UTC),
            )
            session.add(index_entry)
            session.flush()

        return artifact.id


def _seed_transcript_summary(db, *, session_id="sess-summary", summary="Test transcript summary"):
    """Create a project, transcript with summary, and search_index entry. Returns transcript ID."""
    with db.session() as session:
        project = session.query(ProjectSchema).filter(ProjectSchema.name == "test-project").first()
        if project is None:
            project = ProjectSchema(name="test-project", repo_path="/tmp/test")
            session.add(project)
            session.flush()

        transcript = TranscriptSchema(
            project_id=project.id,
            session_id=session_id,
            path=f"/tmp/transcript-{session_id}.jsonl",
            title=f"Title for {session_id}",
            summary=summary,
        )
        session.add(transcript)
        session.flush()

        index_entry = SearchIndexSchema(
            source_type=SearchSourceType.TRANSCRIPT_SUMMARY.value,
            source_id=transcript.id,
            project_id=project.id,
            transcript_id=transcript.id,
            text=summary,
            content_hash=_content_hash(summary),
            embedding=_random_embedding(),
            created_at=datetime.now(UTC),
        )
        session.add(index_entry)
        session.flush()

        return transcript.id


class TestSearchArtifacts:
    def test_returns_artifact_results(self, db):  # noqa: ARG002
        _seed_data(db)

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project")

        assert len(results) >= 1
        result = results[0]
        assert "source_id" in result
        assert "text" in result
        assert "score" in result
        assert "transcript_id" in result
        assert "type" in result
        assert "prompt_event_id" in result
        assert "session_context" in result

    def test_excludes_prompts(self, db):  # noqa: ARG002
        _seed_data(db, artifact_type=ArtifactType.PROMPT, session_id="sess-prompt")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project")

        prompt_results = [r for r in results if r.get("type") == ArtifactType.PROMPT.value]
        assert len(prompt_results) == 0

    def test_excludes_transcript_summaries(self, db):  # noqa: ARG002
        _seed_transcript_summary(db, session_id="sess-excluded")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project")

        # No transcript summary results should appear in artifact search
        for r in results:
            assert "title" not in r

    def test_scopes_to_project(self, db):  # noqa: ARG002
        _seed_data(db, session_id="sess-scoped")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "nonexistent-project")

        assert len(results) == 0

    def test_excludes_current_session(self, db):  # noqa: ARG002
        _seed_data(db, session_id="current-session")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project", session_id="current-session")

        assert len(results) == 0

    def test_respects_top_k(self, db):  # noqa: ARG002
        for i in range(5):
            _seed_data(db, session_id=f"sess-topk-{i}")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project", top_k=2)

        assert len(results) <= 2

    def test_threshold_filters_low_scores(self, db):  # noqa: ARG002
        _seed_data(db, session_id="sess-thresh")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project", threshold=0.99)

        # With random embeddings, scores should be low — most filtered out
        for r in results:
            assert r["score"] >= 0.99

    def test_session_context_includes_siblings(self, db):
        """Results include sibling artifact entries from the same transcript."""
        with db.session() as session:
            project = session.query(ProjectSchema).filter(ProjectSchema.name == "test-project").first()
            if project is None:
                project = ProjectSchema(name="test-project", repo_path="/tmp/test")
                session.add(project)
                session.flush()

            transcript = TranscriptSchema(
                project_id=project.id,
                session_id="sess-siblings",
                path="/tmp/transcript-sess-siblings.jsonl",
            )
            session.add(transcript)
            session.flush()

            primary = ArtifactSchema(
                artifact_type=ArtifactType.KNOWLEDGE.value,
                origin=ArtifactSource.EXTRACTED.value,
                text="primary artifact with embedding",
                transcript_id=transcript.id,
                created_at=datetime.now(UTC),
            )
            sibling = ArtifactSchema(
                artifact_type=ArtifactType.DECISION.value,
                origin=ArtifactSource.EXTRACTED.value,
                text="sibling decision in same session",
                transcript_id=transcript.id,
                created_at=datetime.now(UTC),
            )
            session.add_all([primary, sibling])
            session.flush()
            both_ids = {primary.id, sibling.id}

            for artifact, emb_offset in [(primary, 0), (sibling, 1)]:
                session.add(
                    SearchIndexSchema(
                        source_type=SearchSourceType.ARTIFACT.value,
                        source_id=artifact.id,
                        project_id=project.id,
                        transcript_id=transcript.id,
                        text=artifact.text,
                        content_hash=_content_hash(artifact.text),
                        embedding=_fixed_embedding(base=1.0, offset=emb_offset),
                        created_at=datetime.now(UTC),
                    )
                )
            session.flush()

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project", top_k=1)

        assert len(results) == 1
        result_id = results[0]["source_id"]
        siblings = results[0]["session_context"]
        context_ids = {s["id"] for s in siblings}
        assert context_ids == both_ids - {result_id}
        for s in siblings:
            assert "type" in s

    def test_empty_db_returns_empty(self, db):  # noqa: ARG002
        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("test query", "test-project")

        assert results == []


class TestSearchTranscripts:
    def test_returns_transcript_results(self, db):  # noqa: ARG002
        _seed_transcript_summary(db)

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts("test query", "test-project")

        assert len(results) >= 1
        result = results[0]
        assert "source_id" in result
        assert "text" in result
        assert "score" in result
        assert "title" in result
        assert "transcript_id" in result

    def test_no_session_context(self, db):  # noqa: ARG002
        """Transcript search results should not include session_context."""
        _seed_transcript_summary(db)

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts("test query", "test-project")

        assert len(results) >= 1
        for r in results:
            assert "session_context" not in r

    def test_excludes_artifacts(self, db):  # noqa: ARG002
        _seed_data(db, session_id="sess-excluded")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts("test query", "test-project")

        # No artifact results should appear in transcript search
        for r in results:
            assert "type" not in r
            assert "prompt_event_id" not in r

    def test_scopes_to_project(self, db):  # noqa: ARG002
        _seed_transcript_summary(db, session_id="sess-scoped-ts")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts("test query", "nonexistent-project")

        assert len(results) == 0

    def test_excludes_current_session(self, db):  # noqa: ARG002
        _seed_transcript_summary(db, session_id="current-session-ts")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts("test query", "test-project", session_id="current-session-ts")

        assert len(results) == 0

    def test_respects_top_k(self, db):  # noqa: ARG002
        for i in range(5):
            _seed_transcript_summary(db, session_id=f"sess-topk-ts-{i}", summary=f"Summary {i}")

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts("test query", "test-project", top_k=2)

        assert len(results) <= 2

    def test_empty_db_returns_empty(self, db):  # noqa: ARG002
        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_transcripts("test query", "test-project")

        assert results == []


class TestGetArtifact:
    def test_returns_artifact(self, db):  # noqa: ARG002
        artifact_id = _seed_data(db, session_id="sess-get")

        result = engine.get_artifact(artifact_id)

        assert result is not None
        assert result["id"] == artifact_id
        assert "type" in result
        assert "text" in result
        assert "prompt_event_id" in result

    def test_includes_prompts(self, db):  # noqa: ARG002
        artifact_id = _seed_data(db, artifact_type=ArtifactType.PROMPT, session_id="sess-get-prompt")

        result = engine.get_artifact(artifact_id)

        assert result is not None
        assert result["type"] == ArtifactType.PROMPT.value

    def test_returns_none_for_missing(self, db):  # noqa: ARG002
        result = engine.get_artifact(99999)
        assert result is None


class TestGetTranscriptSummary:
    def test_returns_summary(self, db):  # noqa: ARG002
        transcript_id = _seed_transcript_summary(db, session_id="sess-get-summary")

        result = engine.get_transcript_summary(transcript_id)

        assert result is not None
        assert result["id"] == transcript_id
        assert result["title"] is not None
        assert result["summary"] is not None
        assert result["session_id"] == "sess-get-summary"
        assert "started_at" in result

    def test_returns_none_for_missing(self, db):  # noqa: ARG002
        result = engine.get_transcript_summary(99999)
        assert result is None
