"""Tests for observer.search.engine module."""

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
from observer.search import engine


def _random_embedding() -> list[float]:
    return np.random.rand(EMBEDDING_DIMENSIONS).astype(np.float32).tolist()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _mock_model():
    model = MagicMock()
    model.encode.return_value = np.random.rand(1, EMBEDDING_DIMENSIONS).astype(np.float32)
    return model


def _mock_collection_with_results(
    artifact_ids: list[int],
    distances: list[float] | None = None,
    metadatas: list[dict] | None = None,
):
    """Return a mock ChromaDB collection that returns given results on query."""
    collection = MagicMock()
    if not artifact_ids:
        collection.query.return_value = {"ids": [[]], "distances": [[]], "metadatas": [[]]}
    else:
        if distances is None:
            distances = [0.1] * len(artifact_ids)
        if metadatas is None:
            metadatas = [{}] * len(artifact_ids)
        collection.query.return_value = {
            "ids": [[str(aid) for aid in artifact_ids]],
            "distances": [distances],
            "metadatas": [metadatas],
        }
    return collection


def _seed_artifact(
    db,
    *,
    section_type=SectionType.KNOWLEDGE,
    session_id="sess-1",
    project_name="test-project",
    text=None,
):
    """Create a project, transcript, and indexed artifact. Returns (artifact_id, transcript_id)."""
    if text is None:
        text = f"test extraction of type {section_type.value}"
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
            section_type=section_type,
            text=text,
            content_hash=_content_hash(text),
            indexed_at=datetime.now(UTC),
        )
        session.add(extraction)
        session.flush()

        return extraction.id, transcript.id


def _seed_summary(
    db,
    *,
    session_id="sess-summary",
    summary_text="## Test Title\nTest transcript summary",
    project_name="test-project",
):
    """Create a project, transcript, and indexed summary. Returns transcript ID."""
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
            content_hash=_content_hash(summary_text),
            indexed_at=datetime.now(UTC),
        )
        session.add(extraction)
        session.flush()

        return transcript.id


class TestSearchArtifacts:
    def test_returns_extraction_results(self, db):  # noqa: ARG002
        aid, _ = _seed_artifact(db)
        mock_coll = _mock_collection_with_results(
            [aid], distances=[0.1], metadatas=[{"session_id": "sess-1", "section_type": "knowledge"}]
        )

        with (
            patch.object(engine, "get_model", return_value=_mock_model()),
            patch("observer.search.engine.get_collection", return_value=mock_coll),
        ):
            results = engine.search_artifacts("test query", "test-project")

        assert len(results) >= 1
        result = results[0]
        assert "session_id" in result
        assert "text" in result
        assert "score" in result
        assert "type" in result

    def test_scopes_to_project(self, db):  # noqa: ARG002
        _seed_artifact(db, session_id="sess-scoped")

        with (
            patch.object(engine, "get_model", return_value=_mock_model()),
            patch("observer.search.engine.get_collection", return_value=_mock_collection_with_results([])),
        ):
            results = engine.search_artifacts("test query", "nonexistent-project")

        assert len(results) == 0

    def test_threshold_filters_low_scores(self, db):  # noqa: ARG002
        aid, _ = _seed_artifact(db, session_id="sess-thresh")

        with (
            patch.object(engine, "get_model", return_value=_mock_model()),
            patch(
                "observer.search.engine.get_collection",
                return_value=_mock_collection_with_results(
                    [aid], distances=[0.5], metadatas=[{"session_id": "sess-thresh"}]
                ),
            ),
        ):
            results = engine.search_artifacts("test query", "test-project", threshold=0.99)

        for r in results:
            assert r["score"] >= 0.99

    def test_empty_db_returns_empty(self, db):  # noqa: ARG002
        with (
            patch.object(engine, "get_model", return_value=_mock_model()),
            patch("observer.search.engine.get_collection", return_value=_mock_collection_with_results([])),
        ):
            results = engine.search_artifacts("test query", "test-project")

        assert results == []


class TestHybridRetrieval:
    """Tests for the FTS pathway and merge behavior in hybrid search."""

    def test_keyword_match_surfaces_result(self, db):  # noqa: ARG002
        """An artifact containing query terms is found via FTS even without KNN hit."""
        _seed_artifact(
            db,
            session_id="sess-kw-match",
            text="worktree isolation design prevents polluting project directories",
        )

        with (
            patch.object(engine, "get_model", return_value=_mock_model()),
            patch("observer.search.engine.get_collection", return_value=_mock_collection_with_results([])),
        ):
            results = engine.search_artifacts("worktree isolation", "test-project", threshold=0.0)

        session_ids = [r["session_id"] for r in results]
        assert "sess-kw-match" in session_ids

    def test_fts_finds_unembedded_artifact(self, db):  # noqa: ARG002
        """FTS can surface artifacts that haven't been embedded in ChromaDB."""
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

            # No indexed_at — hasn't been embedded in ChromaDB
            artifact = ArtifactSchema(
                transcript_id=transcript.id,
                section_type=SectionType.KNOWLEDGE,
                text="migration schema version tracking applied automatically",
            )
            session.add(artifact)

        with (
            patch.object(engine, "get_model", return_value=_mock_model()),
            patch("observer.search.engine.get_collection", return_value=_mock_collection_with_results([])),
        ):
            results = engine.search_artifacts("migration schema version", "test-project", threshold=0.0)

        session_ids = [r["session_id"] for r in results]
        assert "sess-no-emb" in session_ids

    def test_fts_respects_scope_filters(self, db):  # noqa: ARG002
        """FTS results are scoped to the same project filters as KNN."""
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
                    content_hash=_content_hash("worktree isolation design pattern implementation"),
                    indexed_at=datetime.now(UTC),
                )
            )

        with (
            patch.object(engine, "get_model", return_value=_mock_model()),
            patch("observer.search.engine.get_collection", return_value=_mock_collection_with_results([])),
        ):
            results = engine.search_artifacts("worktree isolation", "project-a", threshold=0.0)

        session_ids = [r["session_id"] for r in results]
        assert "sess-fts-a" in session_ids
        assert "sess-fts-b" not in session_ids


class TestSearchTranscripts:
    def test_returns_transcript_results(self, db):  # noqa: ARG002
        tid = _seed_summary(db)
        # Get the artifact ID for the summary
        with db.session() as session:
            art = session.query(ArtifactSchema).filter(ArtifactSchema.transcript_id == tid).first()
            aid = art.id

        mock_coll = _mock_collection_with_results(
            [aid], distances=[0.1], metadatas=[{"session_id": "sess-summary", "section_type": "summary"}]
        )

        with (
            patch.object(engine, "get_model", return_value=_mock_model()),
            patch("observer.search.engine.get_collection", return_value=mock_coll),
        ):
            results = engine.search_transcripts("test query", "test-project")

        assert len(results) >= 1
        result = results[0]
        assert "session_id" in result
        assert "text" in result
        assert "score" in result
        assert "title" in result

    def test_scopes_to_project(self, db):  # noqa: ARG002
        _seed_summary(db, session_id="sess-scoped-ts")

        with (
            patch.object(engine, "get_model", return_value=_mock_model()),
            patch("observer.search.engine.get_collection", return_value=_mock_collection_with_results([])),
        ):
            results = engine.search_transcripts("test query", "nonexistent-project")

        assert len(results) == 0

    def test_empty_db_returns_empty(self, db):  # noqa: ARG002
        with (
            patch.object(engine, "get_model", return_value=_mock_model()),
            patch("observer.search.engine.get_collection", return_value=_mock_collection_with_results([])),
        ):
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
