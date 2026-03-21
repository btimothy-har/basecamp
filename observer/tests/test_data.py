"""Tests for observer Pydantic domain models."""

from datetime import UTC, datetime

from observer.data import (
    Project,
    RawEvent,
    Transcript,
    Worktree,
)
from observer.data.schemas import (
    ProjectSchema,
    RawEventSchema,
    TranscriptEventSchema,
    TranscriptSchema,
    WorkItemSchema,
    WorktreeSchema,
)
NOW = datetime.now(UTC)


class TestProjectModel:
    def test_construction(self):
        p = Project(name="proj", repo_path="/repo")
        assert p.id is None
        assert p.name == "proj"
        assert p.repo_path == "/repo"
        assert p.worktrees == []
        assert p.transcripts == []

    def test_with_id(self):
        p = Project(id=1, name="proj", repo_path="/repo")
        assert p.id == 1

    def test_with_nested_worktrees(self):
        wt = Worktree(id=1, project_id=1, label="feat", path="/wt", branch="main")
        p = Project(id=1, name="proj", repo_path="/repo", worktrees=[wt])
        assert len(p.worktrees) == 1
        assert p.worktrees[0].label == "feat"

    def test_from_attributes(self, db):  # noqa: ARG002
        with db.session() as s:
            row = ProjectSchema(name="proj", repo_path="/repo")
            s.add(row)
            s.flush()
            p = Project.model_validate(row)
            assert p.id == row.id
            assert p.name == "proj"

    def test_from_attributes_with_worktrees(self, db):  # noqa: ARG002
        with db.session() as s:
            row = ProjectSchema(name="proj", repo_path="/repo")
            s.add(row)
            s.flush()
            wt = WorktreeSchema(project_id=row.id, label="feat", path="/wt", branch="main")
            s.add(wt)
            s.flush()
            p = Project.model_validate(row)
            assert len(p.worktrees) == 1
            assert p.worktrees[0].label == "feat"


class TestWorktreeModel:
    def test_construction(self):
        w = Worktree(project_id=1, label="feat", path="/wt", branch="main")
        assert w.id is None
        assert w.project_id == 1

    def test_from_attributes(self, db):  # noqa: ARG002
        with db.session() as s:
            proj = ProjectSchema(name="proj", repo_path="/repo")
            s.add(proj)
            s.flush()
            row = WorktreeSchema(project_id=proj.id, label="feat", path="/wt", branch="main")
            s.add(row)
            s.flush()
            w = Worktree.model_validate(row)
            assert w.id == row.id
            assert w.project_id == proj.id


class TestTranscriptModel:
    def test_construction(self):
        t = Transcript(project_id=1, session_id="s1", path="/t", started_at=NOW)
        assert t.id is None
        assert t.worktree_id is None
        assert t.cursor_offset == 0
        assert t.ended_at is None
        assert t.raw_events == []

    def test_from_attributes(self, db):  # noqa: ARG002
        with db.session() as s:
            proj = ProjectSchema(name="proj", repo_path="/repo")
            s.add(proj)
            s.flush()
            row = TranscriptSchema(project_id=proj.id, session_id="s1", path="/t")
            s.add(row)
            s.flush()
            t = Transcript.model_validate(row)
            assert t.id == row.id
            assert t.started_at is not None


class TestRawEventModel:
    def test_construction(self):
        e = RawEvent(
            transcript_id=1,
            event_type="msg",
            timestamp=NOW,
            content="hello",
        )
        assert e.id is None
        assert e.message_uuid is None
        assert e.processed == 0

    def test_from_attributes(self, db):  # noqa: ARG002
        with db.session() as s:
            proj = ProjectSchema(name="proj", repo_path="/repo")
            s.add(proj)
            s.flush()
            tr = TranscriptSchema(project_id=proj.id, session_id="s1", path="/t")
            s.add(tr)
            s.flush()
            row = RawEventSchema(
                transcript_id=tr.id,
                event_type="msg",
                timestamp=NOW,
                content="hello",
            )
            s.add(row)
            s.flush()
            e = RawEvent.model_validate(row)
            assert e.id == row.id
            assert e.event_type == "msg"


class TestLookupMethods:
    def test_project_get_by_repo_path(self, db):  # noqa: ARG002
        with db.session() as s:
            row = ProjectSchema(name="proj", repo_path="/repo")
            s.add(row)
            s.flush()
        p = Project.get_by_repo_path("/repo")
        assert p is not None
        assert p.name == "proj"

    def test_project_get_by_repo_path_not_found(self, db):  # noqa: ARG002
        assert Project.get_by_repo_path("/nonexistent") is None

    def test_worktree_get_by_project_and_label(self, db):  # noqa: ARG002
        with db.session() as s:
            proj = ProjectSchema(name="proj", repo_path="/repo")
            s.add(proj)
            s.flush()
            proj_id = proj.id
            wt = WorktreeSchema(project_id=proj_id, label="feat", path="/wt", branch="main")
            s.add(wt)
            s.flush()
        w = Worktree.get_by_project_and_label(proj_id, "feat")
        assert w is not None
        assert w.label == "feat"

    def test_worktree_get_by_project_and_label_not_found(self, db):  # noqa: ARG002
        assert Worktree.get_by_project_and_label(999, "nope") is None

    def test_transcript_get_by_session_id(self, db):  # noqa: ARG002
        with db.session() as s:
            proj = ProjectSchema(name="proj", repo_path="/repo")
            s.add(proj)
            s.flush()
            tr = TranscriptSchema(project_id=proj.id, session_id="s1", path="/t")
            s.add(tr)
            s.flush()
        t = Transcript.get_by_session_id("s1")
        assert t is not None
        assert t.session_id == "s1"

    def test_transcript_get_by_session_id_not_found(self, db):  # noqa: ARG002
        assert Transcript.get_by_session_id("nonexistent") is None
