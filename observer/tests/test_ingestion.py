"""Tests for Active Record methods and ingestion pipeline."""

import json
from datetime import UTC, datetime

import pytest
from observer.data.enums import RawEventStatus
from observer.data.project import Project
from observer.data.raw_event import RawEvent
from observer.data.schemas import RawEventSchema
from observer.data.transcript import Transcript
from observer.data.worktree import Worktree
from observer.pipeline.parser import TranscriptParser

from tests.pi_fixtures import (
    make_assistant_message,
    make_session_header,
    make_tool_result,
    make_user_message,
)

NOW = datetime.now(UTC)


def _write_jsonl(path, lines: list[dict]) -> None:
    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def _make_event(
    event_type: str = "user",
    timestamp: str = "2025-01-15T10:00:00Z",
    uuid: str | None = "abc-123",
) -> dict:
    d: dict = {"type": event_type, "timestamp": timestamp}
    if uuid is not None:
        d["uuid"] = uuid
    return d


# -- Project save/get ---------------------------------------------------------


class TestProjectSaveGet:
    def test_save_new(self, db):  # noqa: ARG002
        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            assert p.id is not None
            assert p.name == "proj"

    def test_save_update(self, db):  # noqa: ARG002
        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            p.repo_path = "/new"
            p = p.save(s)
            assert p.repo_path == "/new"

    def test_get_exists(self, db):  # noqa: ARG002
        with db.session() as s:
            saved = Project(name="proj", repo_path="/repo").save(s)
        loaded = Project.get(saved.id)
        assert loaded is not None
        assert loaded.name == "proj"

    def test_get_missing(self, db):  # noqa: ARG002
        assert Project.get(999) is None


# -- Worktree save/get --------------------------------------------------------


class TestWorktreeSaveGet:
    def test_save_new(self, db):  # noqa: ARG002
        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            w = Worktree(project_id=p.id, label="feat", path="/wt", branch="main").save(s)
            assert w.id is not None

    def test_save_update(self, db):  # noqa: ARG002
        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            w = Worktree(project_id=p.id, label="feat", path="/wt", branch="main").save(s)
            w.branch = "dev"
            w = w.save(s)
            assert w.branch == "dev"

    def test_get_exists(self, db):  # noqa: ARG002
        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            saved = Worktree(project_id=p.id, label="feat", path="/wt", branch="main").save(s)
        loaded = Worktree.get(saved.id)
        assert loaded is not None
        assert loaded.label == "feat"

    def test_get_missing(self, db):  # noqa: ARG002
        assert Worktree.get(999) is None


# -- Transcript save/get/get_active -------------------------------------------


class TestTranscriptSaveGet:
    def test_save_new(self, db):  # noqa: ARG002
        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            t = Transcript(project_id=p.id, session_id="s1", path="/t", started_at=NOW).save(s)
            assert t.id is not None
            assert t.cursor_offset == 0

    def test_save_update(self, db):  # noqa: ARG002
        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            t = Transcript(project_id=p.id, session_id="s1", path="/t", started_at=NOW).save(s)
            t.cursor_offset = 100
            t = t.save(s)
            assert t.cursor_offset == 100

    def test_get_exists(self, db):  # noqa: ARG002
        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            saved = Transcript(project_id=p.id, session_id="s1", path="/t", started_at=NOW).save(s)
        loaded = Transcript.get(saved.id)
        assert loaded is not None
        assert loaded.session_id == "s1"

    def test_get_missing(self, db):  # noqa: ARG002
        assert Transcript.get(999) is None


# -- RawEvent save/get --------------------------------------------------------


class TestRawEventSaveGet:
    def test_save_new(self, db):  # noqa: ARG002
        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            t = Transcript(project_id=p.id, session_id="s1", path="/t", started_at=NOW).save(s)
            e = RawEvent(
                transcript_id=t.id,
                event_type="user",
                timestamp=NOW,
                content="hello",
            ).save(s)
            assert e.id is not None

    def test_save_update(self, db):  # noqa: ARG002
        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            t = Transcript(project_id=p.id, session_id="s1", path="/t", started_at=NOW).save(s)
            e = RawEvent(
                transcript_id=t.id,
                event_type="user",
                timestamp=NOW,
                content="hello",
            ).save(s)
            e.processed = RawEventStatus.PROCESSED
            e = e.save(s)
            assert e.processed == 1

    def test_get_exists(self, db):  # noqa: ARG002
        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            t = Transcript(project_id=p.id, session_id="s1", path="/t", started_at=NOW).save(s)
            saved = RawEvent(
                transcript_id=t.id,
                event_type="user",
                timestamp=NOW,
                content="hello",
            ).save(s)
        loaded = RawEvent.get(saved.id)
        assert loaded is not None
        assert loaded.event_type == "user"

    def test_get_missing(self, db):  # noqa: ARG002
        assert RawEvent.get(999) is None


# -- Ingestion ----------------------------------------------------------------


class TestIngestTranscript:
    def _setup(self, db, tmp_path):
        """Create a project and transcript pointing at a tmp_path file."""
        transcript_path = tmp_path / "transcript.jsonl"
        transcript_path.write_text("")
        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            t = Transcript(
                project_id=p.id,
                session_id="s1",
                path=str(transcript_path),
                started_at=NOW,
            ).save(s)
        return t, transcript_path

    def test_ingest_empty_file(self, db, tmp_path):
        t, path = self._setup(db, tmp_path)
        count = TranscriptParser().ingest(t)
        assert count == 0

    def test_ingest_events(self, db, tmp_path):
        t, path = self._setup(db, tmp_path)
        _write_jsonl(
            path,
            [
                _make_event("user", uuid="u-1"),
                _make_event("assistant", uuid="a-1"),
            ],
        )

        count = TranscriptParser().ingest(t)
        assert count == 2

        # Verify events persisted
        loaded = Transcript.get(t.id)
        assert loaded.cursor_offset > 0

    def test_ingest_incremental(self, db, tmp_path):
        t, path = self._setup(db, tmp_path)
        _write_jsonl(path, [_make_event("user", uuid="u-1")])

        count1 = TranscriptParser().ingest(t)
        t = Transcript.get(t.id)

        # Append more events
        with open(path, "a") as f:
            f.write(json.dumps(_make_event("assistant", uuid="a-1")) + "\n")

        count2 = TranscriptParser().ingest(t)

        assert count1 == 1
        assert count2 == 1

    def test_ingest_no_new_events(self, db, tmp_path):
        t, path = self._setup(db, tmp_path)
        _write_jsonl(path, [_make_event("user", uuid="u-1")])

        TranscriptParser().ingest(t)
        t = Transcript.get(t.id)

        count = TranscriptParser().ingest(t)
        assert count == 0

    def test_ingest_unsaved_transcript(self, db):  # noqa: ARG002
        t = Transcript(project_id=1, session_id="s1", path="/t", started_at=NOW)
        with pytest.raises(ValueError, match="must be saved"):
            TranscriptParser().ingest(t)

    def test_ingest_missing_file(self, db, tmp_path):
        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            t = Transcript(
                project_id=p.id,
                session_id="s1",
                path=str(tmp_path / "nonexistent.jsonl"),
                started_at=NOW,
            ).save(s)

        with pytest.raises(FileNotFoundError):
            TranscriptParser().ingest(t)


# -- Pi-format ingestion -------------------------------------------------------


class TestIngestPiTranscript:
    """Integration tests for pi-format JSONL ingestion."""

    def _setup(self, db, tmp_path):
        transcript_path = tmp_path / "session.jsonl"
        transcript_path.write_text("")
        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            t = Transcript(
                project_id=p.id,
                session_id="pi-s1",
                path=str(transcript_path),
                started_at=NOW,
            ).save(s)
        return t, transcript_path

    def _write_lines(self, path, lines: list[str]):
        with open(path, "w") as f:
            for line in lines:
                f.write(line + "\n")

    def test_ingest_pi_session(self, db, tmp_path):
        t, path = self._setup(db, tmp_path)
        self._write_lines(
            path,
            [
                make_session_header(session_id="pi-s1"),
                make_user_message("hello", entry_id="a1"),
                make_assistant_message(text="hi", entry_id="b1"),
            ],
        )

        count = TranscriptParser().ingest(t)
        assert count == 2  # session header skipped

        loaded = Transcript.get(t.id)
        assert loaded.cursor_offset > 0

    def test_ingest_pi_source_stored(self, db, tmp_path):
        """Ingested pi events have source='pi' in the database."""
        t, path = self._setup(db, tmp_path)
        self._write_lines(
            path,
            [
                make_user_message("test", entry_id="a1"),
            ],
        )

        TranscriptParser().ingest(t)

        with db.session() as s:
            rows = s.query(RawEventSchema).filter_by(transcript_id=t.id).all()
            assert len(rows) == 1
            assert rows[0].source == "pi"
            assert rows[0].event_type == "user"
            assert rows[0].message_uuid == "a1"

    def test_ingest_pi_tool_result(self, db, tmp_path):
        t, path = self._setup(db, tmp_path)
        self._write_lines(
            path,
            [
                make_assistant_message(
                    tool_calls=[{"id": "tc-1", "name": "read", "arguments": {"path": "/a.py"}}],
                    entry_id="b1",
                ),
                make_tool_result("tc-1", "read", "file contents", entry_id="c1"),
            ],
        )

        count = TranscriptParser().ingest(t)
        assert count == 2

        with db.session() as s:
            rows = s.query(RawEventSchema).filter_by(transcript_id=t.id).order_by(RawEventSchema.id).all()
            assert rows[0].event_type == "assistant"
            assert rows[1].event_type == "toolResult"
            assert all(r.source == "pi" for r in rows)

    def test_ingest_pi_incremental(self, db, tmp_path):
        t, path = self._setup(db, tmp_path)
        self._write_lines(path, [make_user_message("first", entry_id="a1")])

        count1 = TranscriptParser().ingest(t)
        t = Transcript.get(t.id)

        with open(path, "a") as f:
            f.write(make_assistant_message(text="second", entry_id="b1") + "\n")

        count2 = TranscriptParser().ingest(t)
        assert count1 == 1
        assert count2 == 1
