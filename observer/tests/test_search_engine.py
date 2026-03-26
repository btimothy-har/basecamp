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

    def test_unembedded_artifact_without_keyword_match_excluded(self, db):  # noqa: ARG002
        """An artifact with no embedding and no keyword match is excluded from results.

        FTS could surface it if the query terms matched the artifact text, but
        KNN filtering requires an embedding — so only FTS acts as the safety net here.
        """
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


class TestHybridRetrieval:
    """Tests for the FTS pathway and merge behavior in hybrid search."""

    def test_keyword_match_surfaces_result(self, db):  # noqa: ARG002
        """An artifact containing query terms is found even with orthogonal embedding."""
        # Orthogonal embedding — KNN won't rank this well
        far_vec = np.zeros(EMBEDDING_DIMENSIONS, dtype=np.float32)
        far_vec[0] = 1.0

        _seed_artifact(db, session_id="sess-kw")

        # Seed an artifact whose text contains the query keywords
        with db.session() as session:
            project = session.query(ProjectSchema).filter(ProjectSchema.name == "test-project").first()
            transcript = TranscriptSchema(
                project_id=project.id,
                session_id="sess-kw-match",
                path="/tmp/transcript-sess-kw-match.jsonl",
            )
            session.add(transcript)
            session.flush()

            artifact = ArtifactSchema(
                transcript_id=transcript.id,
                section_type=SectionType.KNOWLEDGE,
                text="worktree isolation design prevents polluting project directories",
                embedding=far_vec.tolist(),
                content_hash=_content_hash("worktree isolation design prevents polluting project directories"),
                indexed_at=datetime.now(UTC),
            )
            session.add(artifact)

        # Query uses a term that appears in the artifact text
        model = MagicMock()
        # Query vector orthogonal to far_vec — low semantic similarity
        query_vec = np.zeros(EMBEDDING_DIMENSIONS, dtype=np.float32)
        query_vec[1] = 1.0
        model.encode.return_value = query_vec.reshape(1, -1)

        with patch.object(engine, "_get_model", return_value=model):
            results = engine.search_artifacts("worktree isolation", "test-project", threshold=0.0)

        # The keyword-matching artifact should appear in results
        session_ids = [r["session_id"] for r in results]
        assert "sess-kw-match" in session_ids

    def test_fts_finds_unembedded_artifact(self, db):  # noqa: ARG002
        """FTS can surface artifacts that haven't been embedded yet."""
        with db.session() as session:
            project = ProjectSchema(name="test-project", repo_path="/tmp/test-project")
            session.add(project)
            session.flush()

            transcript = TranscriptSchema(
                project_id=project.id,
                session_id="sess-no-emb",
                path="/tmp/transcript-sess-no-emb.jsonl",
            )
            session.add(transcript)
            session.flush()

            # No embedding set — KNN can't find this
            artifact = ArtifactSchema(
                transcript_id=transcript.id,
                section_type=SectionType.KNOWLEDGE,
                text="migration schema version tracking applied automatically",
            )
            session.add(artifact)

        model = MagicMock()
        model.encode.return_value = np.random.rand(1, EMBEDDING_DIMENSIONS).astype(np.float32)

        with patch.object(engine, "_get_model", return_value=model):
            results = engine.search_artifacts("migration schema version", "test-project", threshold=0.0)

        session_ids = [r["session_id"] for r in results]
        assert "sess-no-emb" in session_ids

    def test_dual_match_scores_higher_than_single(self, db):  # noqa: ARG002
        """An artifact matching both KNN and FTS should score higher than one matching only KNN."""
        # Unit vector — will be used as both query and "close" embedding
        close_vec = np.zeros(EMBEDDING_DIMENSIONS, dtype=np.float32)
        close_vec[0] = 1.0

        with db.session() as session:
            project = ProjectSchema(name="test-project", repo_path="/tmp/test-project")
            session.add(project)
            session.flush()

            # Artifact 1: matches KNN (close embedding) AND FTS (contains query terms)
            t1 = TranscriptSchema(project_id=project.id, session_id="sess-dual", path="/tmp/t-dual.jsonl")
            session.add(t1)
            session.flush()
            a1 = ArtifactSchema(
                transcript_id=t1.id,
                section_type=SectionType.KNOWLEDGE,
                text="database migration handling automatic schema upgrades",
                embedding=close_vec.tolist(),
                content_hash=_content_hash("database migration handling automatic schema upgrades"),
                indexed_at=datetime.now(UTC),
            )
            session.add(a1)

            # Artifact 2: matches KNN (close embedding) but NOT FTS (different terms)
            t2 = TranscriptSchema(project_id=project.id, session_id="sess-knn-only", path="/tmp/t-knn.jsonl")
            session.add(t2)
            session.flush()
            a2 = ArtifactSchema(
                transcript_id=t2.id,
                section_type=SectionType.KNOWLEDGE,
                text="vector embedding cosine similarity search implementation",
                embedding=close_vec.tolist(),
                content_hash=_content_hash("vector embedding cosine similarity search implementation"),
                indexed_at=datetime.now(UTC),
            )
            session.add(a2)

        model = MagicMock()
        model.encode.return_value = close_vec.reshape(1, -1)

        with patch.object(engine, "_get_model", return_value=model):
            results = engine.search_artifacts("database migration schema", "test-project", threshold=0.0)

        # Both should appear, but the dual-match should score higher
        scores = {r["session_id"]: r["score"] for r in results}
        assert "sess-dual" in scores
        assert "sess-knn-only" in scores
        assert scores["sess-dual"] > scores["sess-knn-only"]

    def test_fts_respects_scope_filters(self, db):  # noqa: ARG002
        """FTS results are scoped to the same project/session filters as KNN."""
        with db.session() as session:
            # Project A
            proj_a = ProjectSchema(name="project-a", repo_path="/tmp/project-a")
            session.add(proj_a)
            session.flush()
            t_a = TranscriptSchema(project_id=proj_a.id, session_id="sess-fts-a", path="/tmp/t-fts-a.jsonl")
            session.add(t_a)
            session.flush()
            session.add(
                ArtifactSchema(
                    transcript_id=t_a.id,
                    section_type=SectionType.KNOWLEDGE,
                    text="worktree isolation design pattern implementation",
                    embedding=_random_embedding(),
                    content_hash=_content_hash("worktree isolation design pattern implementation"),
                    indexed_at=datetime.now(UTC),
                )
            )

            # Project B — same text, different project
            proj_b = ProjectSchema(name="project-b", repo_path="/tmp/project-b")
            session.add(proj_b)
            session.flush()
            t_b = TranscriptSchema(project_id=proj_b.id, session_id="sess-fts-b", path="/tmp/t-fts-b.jsonl")
            session.add(t_b)
            session.flush()
            session.add(
                ArtifactSchema(
                    transcript_id=t_b.id,
                    section_type=SectionType.KNOWLEDGE,
                    text="worktree isolation design pattern implementation",
                    embedding=_random_embedding(),
                    content_hash=_content_hash("worktree isolation design pattern implementation"),
                    indexed_at=datetime.now(UTC),
                )
            )

        with patch.object(engine, "_get_model", return_value=_mock_model()):
            results = engine.search_artifacts("worktree isolation", "project-a", threshold=0.0)

        session_ids = [r["session_id"] for r in results]
        assert "sess-fts-a" in session_ids
        assert "sess-fts-b" not in session_ids


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


def _seed_with_dates(
    db,
    *,
    session_id,
    started_at,
    project_name="test-project",
    section_type=SectionType.SUMMARY,
    text=None,
):
    """Create a project, transcript, and artifact with explicit timestamps."""
    if text is None:
        text = f"## {session_id}\nSummary for {session_id}"
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
            started_at=started_at,
        )
        session.add(transcript)
        session.flush()

        artifact = ArtifactSchema(
            transcript_id=transcript.id,
            section_type=section_type,
            text=text,
            created_at=started_at,
        )
        session.add(artifact)


class TestListTranscripts:
    def test_returns_summaries_ordered_by_date(self, db):  # noqa: ARG002
        _seed_with_dates(db, session_id="old", started_at=datetime(2026, 1, 1, tzinfo=UTC))
        _seed_with_dates(db, session_id="new", started_at=datetime(2026, 3, 1, tzinfo=UTC))

        results = engine.list_transcripts("test-project")

        assert len(results) == 2
        assert results[0]["session_id"] == "new"
        assert results[1]["session_id"] == "old"

    def test_after_filter(self, db):  # noqa: ARG002
        _seed_with_dates(db, session_id="jan", started_at=datetime(2026, 1, 15, tzinfo=UTC))
        _seed_with_dates(db, session_id="mar", started_at=datetime(2026, 3, 15, tzinfo=UTC))

        results = engine.list_transcripts("test-project", after=datetime(2026, 2, 1, tzinfo=UTC))

        assert len(results) == 1
        assert results[0]["session_id"] == "mar"

    def test_before_filter(self, db):  # noqa: ARG002
        _seed_with_dates(db, session_id="jan", started_at=datetime(2026, 1, 15, tzinfo=UTC))
        _seed_with_dates(db, session_id="mar", started_at=datetime(2026, 3, 15, tzinfo=UTC))

        results = engine.list_transcripts("test-project", before=datetime(2026, 2, 1, tzinfo=UTC))

        assert len(results) == 1
        assert results[0]["session_id"] == "jan"

    def test_date_range(self, db):  # noqa: ARG002
        _seed_with_dates(db, session_id="jan", started_at=datetime(2026, 1, 15, tzinfo=UTC))
        _seed_with_dates(db, session_id="feb", started_at=datetime(2026, 2, 15, tzinfo=UTC))
        _seed_with_dates(db, session_id="mar", started_at=datetime(2026, 3, 15, tzinfo=UTC))

        results = engine.list_transcripts(
            "test-project",
            after=datetime(2026, 2, 1, tzinfo=UTC),
            before=datetime(2026, 3, 1, tzinfo=UTC),
        )

        assert len(results) == 1
        assert results[0]["session_id"] == "feb"

    def test_scopes_to_project(self, db):  # noqa: ARG002
        _seed_with_dates(db, session_id="s1", started_at=datetime(2026, 1, 1, tzinfo=UTC), project_name="proj-a")
        _seed_with_dates(db, session_id="s2", started_at=datetime(2026, 1, 1, tzinfo=UTC), project_name="proj-b")

        results = engine.list_transcripts("proj-a")

        assert len(results) == 1
        assert results[0]["session_id"] == "s1"

    def test_none_project_returns_all(self, db):  # noqa: ARG002
        _seed_with_dates(db, session_id="a1", started_at=datetime(2026, 1, 1, tzinfo=UTC), project_name="proj-a")
        _seed_with_dates(db, session_id="b1", started_at=datetime(2026, 1, 1, tzinfo=UTC), project_name="proj-b")

        results = engine.list_transcripts(None)

        assert len(results) >= 2

    def test_respects_top_k(self, db):  # noqa: ARG002
        for i in range(5):
            _seed_with_dates(db, session_id=f"s-{i}", started_at=datetime(2026, 1, i + 1, tzinfo=UTC))

        results = engine.list_transcripts("test-project", top_k=2)

        assert len(results) == 2

    def test_includes_title(self, db):  # noqa: ARG002
        _seed_with_dates(
            db, session_id="titled", started_at=datetime(2026, 1, 1, tzinfo=UTC), text="## My Title\nSome content"
        )

        results = engine.list_transcripts("test-project")

        assert results[0]["title"] == "My Title"

    def test_result_has_expected_fields(self, db):  # noqa: ARG002
        _seed_with_dates(db, session_id="fields", started_at=datetime(2026, 1, 1, tzinfo=UTC))

        results = engine.list_transcripts("test-project")

        result = results[0]
        assert "session_id" in result
        assert "text" in result
        assert "started_at" in result
        assert "ended_at" in result
        assert "score" not in result

    def test_empty_db_returns_empty(self, db):  # noqa: ARG002
        results = engine.list_transcripts("test-project")
        assert results == []


class TestListArtifacts:
    def test_returns_artifacts_ordered_by_created_at(self, db):  # noqa: ARG002
        _seed_with_dates(
            db,
            session_id="old",
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            section_type=SectionType.KNOWLEDGE,
            text="old knowledge",
        )
        _seed_with_dates(
            db,
            session_id="new",
            started_at=datetime(2026, 3, 1, tzinfo=UTC),
            section_type=SectionType.KNOWLEDGE,
            text="new knowledge",
        )

        results = engine.list_artifacts("test-project")

        assert len(results) == 2
        assert results[0]["session_id"] == "new"

    def test_after_filter_uses_artifact_created_at(self, db):  # noqa: ARG002
        _seed_with_dates(
            db,
            session_id="jan",
            started_at=datetime(2026, 1, 15, tzinfo=UTC),
            section_type=SectionType.DECISIONS,
            text="jan decision",
        )
        _seed_with_dates(
            db,
            session_id="mar",
            started_at=datetime(2026, 3, 15, tzinfo=UTC),
            section_type=SectionType.DECISIONS,
            text="mar decision",
        )

        results = engine.list_artifacts("test-project", after=datetime(2026, 2, 1, tzinfo=UTC))

        assert len(results) == 1
        assert results[0]["session_id"] == "mar"

    def test_before_filter(self, db):  # noqa: ARG002
        _seed_with_dates(
            db,
            session_id="jan",
            started_at=datetime(2026, 1, 15, tzinfo=UTC),
            section_type=SectionType.KNOWLEDGE,
            text="jan knowledge",
        )
        _seed_with_dates(
            db,
            session_id="mar",
            started_at=datetime(2026, 3, 15, tzinfo=UTC),
            section_type=SectionType.KNOWLEDGE,
            text="mar knowledge",
        )

        results = engine.list_artifacts("test-project", before=datetime(2026, 2, 1, tzinfo=UTC))

        assert len(results) == 1
        assert results[0]["session_id"] == "jan"

    def test_section_types_filter(self, db):  # noqa: ARG002
        _seed_with_dates(
            db,
            session_id="k",
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            section_type=SectionType.KNOWLEDGE,
            text="some knowledge",
        )
        _seed_with_dates(
            db,
            session_id="d",
            started_at=datetime(2026, 1, 2, tzinfo=UTC),
            section_type=SectionType.DECISIONS,
            text="some decision",
        )

        results = engine.list_artifacts("test-project", section_types=["decisions"])

        assert len(results) == 1
        assert results[0]["type"] == SectionType.DECISIONS

    def test_session_id_inclusion(self, db):  # noqa: ARG002
        _seed_with_dates(
            db,
            session_id="target",
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            section_type=SectionType.KNOWLEDGE,
            text="target knowledge",
        )
        _seed_with_dates(
            db,
            session_id="other",
            started_at=datetime(2026, 1, 2, tzinfo=UTC),
            section_type=SectionType.KNOWLEDGE,
            text="other knowledge",
        )

        results = engine.list_artifacts("test-project", session_id="target")

        assert len(results) == 1
        assert results[0]["session_id"] == "target"

    def test_excludes_summaries_by_default(self, db):  # noqa: ARG002
        _seed_with_dates(db, session_id="sum", started_at=datetime(2026, 1, 1, tzinfo=UTC))

        results = engine.list_artifacts("test-project")

        for r in results:
            assert r["type"] != SectionType.SUMMARY

    def test_scopes_to_project(self, db):  # noqa: ARG002
        _seed_with_dates(
            db,
            session_id="a",
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            project_name="proj-a",
            section_type=SectionType.KNOWLEDGE,
            text="a knowledge",
        )
        _seed_with_dates(
            db,
            session_id="b",
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            project_name="proj-b",
            section_type=SectionType.KNOWLEDGE,
            text="b knowledge",
        )

        results = engine.list_artifacts("proj-a")

        assert all(r["session_id"] == "a" for r in results)

    def test_result_has_expected_fields(self, db):  # noqa: ARG002
        _seed_with_dates(
            db,
            session_id="fields",
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            section_type=SectionType.KNOWLEDGE,
            text="knowledge",
        )

        results = engine.list_artifacts("test-project")

        result = results[0]
        assert "session_id" in result
        assert "text" in result
        assert "type" in result
        assert "created_at" in result
        assert "started_at" in result
        assert "ended_at" in result
        assert "score" not in result

    def test_empty_db_returns_empty(self, db):  # noqa: ARG002
        results = engine.list_artifacts("test-project")
        assert results == []
