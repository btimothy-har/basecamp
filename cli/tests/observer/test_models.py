"""Tests for observer SQLAlchemy schemas."""

from datetime import UTC, datetime

import pytest
from observer.data.enums import SectionType
from observer.data.schemas import (
    ArtifactSchema,
    ProjectSchema,
    RawEventSchema,
    TranscriptSchema,
    WorktreeSchema,
)
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError


def _make_project(session, name="proj", repo_path="/repo") -> ProjectSchema:
    p = ProjectSchema(name=name, repo_path=repo_path)
    session.add(p)
    session.flush()
    return p


def _make_worktree(session, project, label="wt", path="/wt", branch="main") -> WorktreeSchema:
    w = WorktreeSchema(project_id=project.id, label=label, path=path, branch=branch)
    session.add(w)
    session.flush()
    return w


def _make_transcript(session, project, *, worktree=None, session_id="s1", path="/t") -> TranscriptSchema:
    t = TranscriptSchema(
        project_id=project.id,
        worktree_id=worktree.id if worktree else None,
        session_id=session_id,
        path=path,
    )
    session.add(t)
    session.flush()
    return t


def _make_raw_event(session, transcript, *, event_type="msg", content="hello") -> RawEventSchema:
    e = RawEventSchema(
        transcript_id=transcript.id,
        event_type=event_type,
        timestamp=datetime.now(UTC),
        content=content,
    )
    session.add(e)
    session.flush()
    return e


class TestIngestionModels:
    """Tests for Project, Worktree, Transcript, RawEvent."""

    def test_create_project(self, db):
        with db.session() as s:
            p = _make_project(s)
            assert p.id is not None
            assert p.name == "proj"

    def test_project_unique_name(self, db):
        with db.session() as s:
            _make_project(s, name="dup", repo_path="/a")
        with pytest.raises(IntegrityError):
            with db.session() as s:
                _make_project(s, name="dup", repo_path="/b")

    def test_project_unique_repo_path(self, db):
        with db.session() as s:
            _make_project(s, name="a", repo_path="/dup")
        with pytest.raises(IntegrityError):
            with db.session() as s:
                _make_project(s, name="b", repo_path="/dup")

    def test_create_worktree(self, db):
        with db.session() as s:
            p = _make_project(s)
            w = _make_worktree(s, p)
            assert w.id is not None
            assert w.project_id == p.id

    def test_worktree_unique_path(self, db):
        with db.session() as s:
            p = _make_project(s)
            _make_worktree(s, p, label="a", path="/same")
        with pytest.raises(IntegrityError):
            with db.session() as s:
                p = s.get(ProjectSchema, 1)
                _make_worktree(s, p, label="b", path="/same")

    def test_worktree_unique_project_label(self, db):
        with db.session() as s:
            p = _make_project(s)
            _make_worktree(s, p, label="dup", path="/a")
        with pytest.raises(IntegrityError):
            with db.session() as s:
                p = s.get(ProjectSchema, 1)
                _make_worktree(s, p, label="dup", path="/b")

    def test_worktree_relationship(self, db):
        with db.session() as s:
            p = _make_project(s)
            _make_worktree(s, p)
            assert len(p.worktrees) == 1
            assert p.worktrees[0].label == "wt"

    def test_create_transcript(self, db):
        with db.session() as s:
            p = _make_project(s)
            t = _make_transcript(s, p)
            assert t.id is not None
            assert t.cursor_offset == 0
            assert t.started_at is not None
            assert t.ended_at is None

    def test_transcript_nullable_worktree(self, db):
        with db.session() as s:
            p = _make_project(s)
            t = _make_transcript(s, p)
            assert t.worktree_id is None

    def test_transcript_with_worktree(self, db):
        with db.session() as s:
            p = _make_project(s)
            w = _make_worktree(s, p)
            t = _make_transcript(s, p, worktree=w)
            assert t.worktree_id == w.id

    def test_transcript_unique_session_id(self, db):
        with db.session() as s:
            p = _make_project(s)
            _make_transcript(s, p, session_id="dup", path="/a")
        with pytest.raises(IntegrityError):
            with db.session() as s:
                p = s.get(ProjectSchema, 1)
                _make_transcript(s, p, session_id="dup", path="/b")

    def test_transcript_unique_path(self, db):
        with db.session() as s:
            p = _make_project(s)
            _make_transcript(s, p, session_id="a", path="/dup")
        with pytest.raises(IntegrityError):
            with db.session() as s:
                p = s.get(ProjectSchema, 1)
                _make_transcript(s, p, session_id="b", path="/dup")

    def test_transcript_relationship_to_project(self, db):
        with db.session() as s:
            p = _make_project(s)
            _make_transcript(s, p)
            assert len(p.transcripts) == 1

    def test_create_raw_event(self, db):
        with db.session() as s:
            p = _make_project(s)
            t = _make_transcript(s, p)
            e = _make_raw_event(s, t)
            assert e.id is not None
            assert e.processed == 0
            assert e.message_uuid is None
            assert e.source == "pi"  # schema default

    def test_create_raw_event_with_source(self, db):
        with db.session() as s:
            p = _make_project(s)
            t = _make_transcript(s, p)
            e = RawEventSchema(
                transcript_id=t.id,
                event_type="msg",
                timestamp=datetime.now(UTC),
                content="hello",
                source="claude",
            )
            s.add(e)
            s.flush()
            assert e.source == "claude"

    def test_raw_event_relationship(self, db):
        with db.session() as s:
            p = _make_project(s)
            t = _make_transcript(s, p)
            _make_raw_event(s, t)
            assert len(t.raw_events) == 1

    def test_raw_event_fk_enforcement(self, db):
        with pytest.raises(IntegrityError):
            with db.session() as s:
                e = RawEventSchema(
                    transcript_id=9999,
                    event_type="msg",
                    timestamp=datetime.now(UTC),
                    content="orphan",
                )
                s.add(e)
                s.flush()


class TestArtifactModels:
    """Tests for ArtifactSchema."""

    def test_create_artifact(self, db):
        with db.session() as s:
            p = _make_project(s)
            t = _make_transcript(s, p)
            row = ArtifactSchema(
                transcript_id=t.id,
                section_type=SectionType.SUMMARY,
                text="## JWT Auth\nImplemented JWT authentication",
            )
            s.add(row)
            s.flush()
            assert row.id is not None
            assert row.section_type == SectionType.SUMMARY
            assert row.created_at is not None
            assert row.indexed_at is None

    def test_unique_constraint_transcript_section(self, db):
        """Only one row per (transcript_id, section_type)."""
        with db.session() as s:
            p = _make_project(s)
            t = _make_transcript(s, p)
            s.add(
                ArtifactSchema(
                    transcript_id=t.id,
                    section_type=SectionType.KNOWLEDGE,
                    text="first",
                )
            )
            s.flush()
        with pytest.raises(IntegrityError):
            with db.session() as s:
                t_row = s.get(TranscriptSchema, 1)
                s.add(
                    ArtifactSchema(
                        transcript_id=t_row.id,
                        section_type=SectionType.KNOWLEDGE,
                        text="duplicate",
                    )
                )
                s.flush()


class TestSchemaIntegrity:
    """Verify all tables, indexes, and constraints are created."""

    EXPECTED_TABLES = {
        "projects",
        "worktrees",
        "transcripts",
        "raw_events",
        "artifacts",
    }

    def test_all_tables_created(self, db):
        with db.session() as s:
            inspector = inspect(s.bind)
            tables = set(inspector.get_table_names())
            assert self.EXPECTED_TABLES.issubset(tables)

    def test_raw_events_indexes(self, db):
        with db.session() as s:
            inspector = inspect(s.bind)
            indexes = {idx["name"] for idx in inspector.get_indexes("raw_events")}
            assert "ix_raw_events_transcript_id" in indexes
            assert "ix_raw_events_processed" in indexes
            assert "ix_raw_events_event_type" in indexes

    def test_artifacts_indexes(self, db):
        with db.session() as s:
            inspector = inspect(s.bind)
            indexes = {idx["name"] for idx in inspector.get_indexes("artifacts")}
            assert "ix_artifacts_transcript_id" in indexes
            assert "ix_artifacts_section_type" in indexes
