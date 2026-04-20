"""Tests for observer Pydantic domain models."""

import json
from datetime import UTC, datetime, timedelta

from observer.data import (
    Project,
    RawEvent,
    Transcript,
    Worktree,
)
from observer.data.artifact import Artifact
from observer.data.enums import SectionType
from observer.data.schemas import (
    ArtifactSchema,
    ProjectSchema,
    RawEventSchema,
    TranscriptSchema,
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
        assert e.source == "pi"  # default

    def test_construction_with_source(self):
        e = RawEvent(
            transcript_id=1,
            event_type="msg",
            timestamp=NOW,
            content="hello",
            source="claude",
        )
        assert e.source == "claude"

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
                source="claude",
            )
            s.add(row)
            s.flush()
            e = RawEvent.model_validate(row)
            assert e.id == row.id
            assert e.event_type == "msg"
            assert e.source == "claude"


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


class TestArtifactSave:
    """Tests for Artifact.save() upsert behavior."""

    def _seed_transcript(self, db) -> int:
        """Create a project + transcript, return transcript_id."""
        with db.session() as session:
            project = ProjectSchema(name="test-proj", repo_path="/tmp/test")
            session.add(project)
            session.flush()
            transcript = TranscriptSchema(
                project_id=project.id,
                session_id="sess-upsert",
                path="/tmp/transcript.jsonl",
            )
            session.add(transcript)
            session.flush()
            return transcript.id

    def test_insert_creates_new_row(self, db):
        tid = self._seed_transcript(db)
        now = datetime.now(UTC)
        extraction = Artifact(
            transcript_id=tid,
            section_type=SectionType.KNOWLEDGE,
            text="some knowledge",
            created_at=now,
            updated_at=now,
        )
        with db.session() as session:
            saved = extraction.save(session)

        assert saved.id is not None
        assert saved.text == "some knowledge"
        assert saved.section_type == SectionType.KNOWLEDGE

    def test_update_overwrites_text(self, db):
        tid = self._seed_transcript(db)
        now = datetime.now(UTC)
        later = now + timedelta(seconds=10)

        with db.session() as session:
            Artifact(
                transcript_id=tid,
                section_type=SectionType.KNOWLEDGE,
                text="v1",
                created_at=now,
                updated_at=now,
            ).save(session)

        with db.session() as session:
            updated = Artifact(
                transcript_id=tid,
                section_type=SectionType.KNOWLEDGE,
                text="v2",
                created_at=now,
                updated_at=later,
            ).save(session)

        assert updated.text == "v2"

        with db.session() as session:
            count = (
                session.query(ArtifactSchema)
                .filter(
                    ArtifactSchema.transcript_id == tid,
                    ArtifactSchema.section_type == SectionType.KNOWLEDGE,
                )
                .count()
            )
        assert count == 1

    def test_different_section_types_coexist(self, db):
        tid = self._seed_transcript(db)
        now = datetime.now(UTC)

        with db.session() as session:
            Artifact(
                transcript_id=tid,
                section_type=SectionType.KNOWLEDGE,
                text="knowledge",
                created_at=now,
                updated_at=now,
            ).save(session)
            Artifact(
                transcript_id=tid,
                section_type=SectionType.DECISIONS,
                text="decisions",
                created_at=now,
                updated_at=now,
            ).save(session)

        with db.session() as session:
            count = session.query(ArtifactSchema).filter(ArtifactSchema.transcript_id == tid).count()
        assert count == 2

    def test_idempotent_save(self, db):
        """Saving the same data twice doesn't create duplicates."""
        tid = self._seed_transcript(db)
        now = datetime.now(UTC)

        for _ in range(2):
            with db.session() as session:
                Artifact(
                    transcript_id=tid,
                    section_type=SectionType.SUMMARY,
                    text="same text",
                    created_at=now,
                    updated_at=now,
                ).save(session)

        with db.session() as session:
            count = (
                session.query(ArtifactSchema)
                .filter(
                    ArtifactSchema.transcript_id == tid,
                    ArtifactSchema.section_type == SectionType.SUMMARY,
                )
                .count()
            )
        assert count == 1


# ---------------------------------------------------------------------------
# Pi-format RawEvent content parsing tests
# ---------------------------------------------------------------------------


def _pi_event(event_type: str, content: dict, **kwargs) -> RawEvent:
    """Build a RawEvent with pi-format JSON content."""
    return RawEvent(
        id=kwargs.get("id", 1),
        transcript_id=kwargs.get("transcript_id", 1),
        event_type=event_type,
        timestamp=kwargs.get("timestamp", NOW),
        content=json.dumps(content),
        source="pi",
    )


def _claude_event(event_type: str, content: dict, **kwargs) -> RawEvent:
    """Build a RawEvent with Claude-format JSON content."""
    return RawEvent(
        id=kwargs.get("id", 1),
        transcript_id=kwargs.get("transcript_id", 1),
        event_type=event_type,
        timestamp=kwargs.get("timestamp", NOW),
        content=json.dumps(content),
        source="claude",
    )


class TestPiRawEventToolUse:
    """Test tool_use detection and field extraction for pi format."""

    def test_is_tool_use_pi(self):
        event = _pi_event(
            "assistant",
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "toolCall", "id": "tc-1", "name": "read", "arguments": {"path": "/a.py"}}],
                },
            },
        )
        assert event.is_tool_use()

    def test_is_not_tool_use_with_tool_use_block_pi(self):
        """Pi format uses 'toolCall', not 'tool_use'."""
        event = _pi_event(
            "assistant",
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "tc-1", "name": "read", "input": {}}],
                },
            },
        )
        assert not event.is_tool_use()  # Wrong block type for pi

    def test_get_tool_use_ids_pi(self):
        event = _pi_event(
            "assistant",
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "toolCall", "id": "tc-1", "name": "read", "arguments": {}},
                        {"type": "toolCall", "id": "tc-2", "name": "bash", "arguments": {}},
                    ],
                },
            },
        )
        assert event.get_tool_use_ids() == frozenset({"tc-1", "tc-2"})

    def test_get_tool_name_pi(self):
        event = _pi_event(
            "assistant",
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "toolCall", "id": "tc-1", "name": "read", "arguments": {}}],
                },
            },
        )
        assert event.get_tool_name() == "read"

    def test_get_tool_input_pi(self):
        event = _pi_event(
            "assistant",
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "toolCall", "id": "tc-1", "name": "read", "arguments": {"path": "/a.py"}}],
                },
            },
        )
        assert event.get_tool_input() == {"path": "/a.py"}


class TestPiRawEventToolResult:
    """Test tool_result detection and field extraction for pi format."""

    def test_is_tool_result_pi(self):
        event = _pi_event(
            "toolResult",
            {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "tc-1",
                    "toolName": "read",
                    "content": [{"type": "text", "text": "file contents"}],
                },
            },
        )
        assert event.is_tool_result()

    def test_is_tool_result_user_not_tool_result_pi(self):
        """Pi user messages are never tool results."""
        event = _pi_event(
            "user",
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "hello"}],
                },
            },
        )
        assert not event.is_tool_result()

    def test_get_tool_result_ids_pi(self):
        event = _pi_event(
            "toolResult",
            {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "tc-1",
                    "toolName": "read",
                    "content": [{"type": "text", "text": "ok"}],
                },
            },
        )
        assert event.get_tool_result_ids() == frozenset({"tc-1"})

    def test_get_tool_result_id_pi(self):
        event = _pi_event(
            "toolResult",
            {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "tc-1",
                    "toolName": "read",
                    "content": [{"type": "text", "text": "ok"}],
                },
            },
        )
        assert event.get_tool_result_id() == "tc-1"

    def test_get_tool_name_from_result_pi(self):
        event = _pi_event(
            "toolResult",
            {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "tc-1",
                    "toolName": "read",
                    "content": [{"type": "text", "text": "ok"}],
                },
            },
        )
        assert event.get_tool_name() == "read"

    def test_get_tool_result_content_pi(self):
        event = _pi_event(
            "toolResult",
            {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "tc-1",
                    "toolName": "read",
                    "content": [{"type": "text", "text": "file contents here"}],
                },
            },
        )
        assert event.get_tool_result_content() == "file contents here"

    def test_is_extractable_tool_result_pi(self):
        event = _pi_event(
            "toolResult",
            {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "tc-1",
                    "toolName": "read",
                    "content": [{"type": "text", "text": "ok"}],
                },
            },
        )
        assert event.is_extractable()


class TestPiRawEventAssistant:
    """Test assistant event methods for pi format."""

    def test_is_agent_text_pi(self):
        event = _pi_event(
            "assistant",
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "here is my response"}],
                },
            },
        )
        assert event.is_agent_text()
        assert event.extract_agent_text() == "here is my response"

    def test_is_not_agent_text_with_tool_call_pi(self):
        event = _pi_event(
            "assistant",
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "let me read that"},
                        {"type": "toolCall", "id": "tc-1", "name": "read", "arguments": {}},
                    ],
                },
            },
        )
        assert not event.is_agent_text()

    def test_is_thinking_pi(self):
        event = _pi_event(
            "assistant",
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "thinking", "thinking": "deep thoughts"}],
                },
            },
        )
        assert event.is_thinking()
        assert event.extract_thinking_text() == "deep thoughts"

    def test_not_thinking_with_tool_call_pi(self):
        """Thinking + toolCall = not thinking-only."""
        event = _pi_event(
            "assistant",
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "hmm"},
                        {"type": "toolCall", "id": "tc-1", "name": "read", "arguments": {}},
                    ],
                },
            },
        )
        assert not event.is_thinking()


class TestPiRawEventFormat:
    """Test format() and brief_description() for pi format."""

    def test_format_tool_result_pi(self):
        event = _pi_event(
            "toolResult",
            {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "tc-1",
                    "toolName": "read",
                    "content": [{"type": "text", "text": "file contents"}],
                },
            },
        )
        formatted = event.format()
        assert "toolResult: read" in formatted
        assert "file contents" in formatted

    def test_brief_description_tool_result_pi(self):
        event = _pi_event(
            "toolResult",
            {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "tc-1",
                    "toolName": "read",
                    "content": [{"type": "text", "text": "ok"}],
                },
            },
        )
        assert "toolResult: read" in event.brief_description()

    def test_format_tool_call_pi(self):
        event = _pi_event(
            "assistant",
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "toolCall", "id": "tc-1", "name": "read", "arguments": {}}],
                },
            },
        )
        formatted = event.format()
        assert "[Tool: read]" in formatted


class TestClaudeRawEventPreserved:
    """Verify all existing Claude format behavior is preserved."""

    def test_is_tool_use_claude(self):
        event = _claude_event(
            "assistant",
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "tu-1", "name": "Read", "input": {}}],
                },
            },
        )
        assert event.is_tool_use()

    def test_is_tool_result_claude(self):
        event = _claude_event(
            "user",
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "tu-1", "content": "ok"}],
                },
            },
        )
        assert event.is_tool_result()

    def test_get_tool_result_ids_claude(self):
        event = _claude_event(
            "user",
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "tu-1", "content": "ok"}],
                },
            },
        )
        assert event.get_tool_result_ids() == frozenset({"tu-1"})

    def test_get_tool_input_claude(self):
        event = _claude_event(
            "assistant",
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "tu-1", "name": "Read", "input": {"file_path": "/a.py"}}],
                },
            },
        )
        assert event.get_tool_input() == {"file_path": "/a.py"}

    def test_is_meta_filtered_claude(self):
        event = _claude_event(
            "user",
            {
                "type": "user",
                "isMeta": True,
                "message": {"role": "user", "content": "some text"},
            },
        )
        assert not event.is_extractable()

    def test_is_compact_summary_filtered_claude(self):
        event = _claude_event(
            "assistant",
            {
                "type": "assistant",
                "isCompactSummary": True,
                "message": {"role": "assistant", "content": "summary text"},
            },
        )
        assert not event.is_extractable()
