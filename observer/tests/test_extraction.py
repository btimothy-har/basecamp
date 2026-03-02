"""Tests for the WorkItemExtractor pipeline (Extract + Summarize).

All tests simulate post-refine state: WorkItems at REFINED stage with
TranscriptEvents already in the DB. Extraction performs artifact extraction
and summarization, then marks items as TERMINAL.
"""

from datetime import UTC, datetime
from unittest.mock import patch

from observer.data.enums import WorkItemStage, WorkItemType
from observer.data.project import Project
from observer.data.schemas import (
    ArtifactSchema,
    TranscriptEventSchema,
    TranscriptSchema,
)
from observer.data.transcript import Transcript
from observer.data.transcript_event import TranscriptEvent
from observer.data.work_item import WorkItem
from observer.exceptions import ExtractionError
from observer.pipeline.extraction import WorkItemExtractor
from observer.pipeline.models import ExtractedArtifact, ExtractionResult

NOW = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)


def _ts(minute: int = 0) -> datetime:
    return NOW.replace(minute=minute)


class _Setup:
    """Helper to create refined WorkItems with pre-existing TranscriptEvents.

    Simulates the output of the Refine stage: each WorkItem is at REFINED
    stage with an associated TranscriptEvent in the DB.
    """

    def __init__(self, db):
        self.db = db
        self.transcript_id: int | None = None
        self._minute = 0

    def create_transcript(self, summary: str | None = None) -> int:
        with self.db.session() as session:
            p = Project(name="proj", repo_path="/repo").save(session)
            t = Transcript(
                project_id=p.id,
                session_id="s1",
                path="/t.jsonl",
                started_at=NOW,
            ).save(session)
        self.transcript_id = t.id

        if summary:
            with self.db.session() as session:
                row = session.get(TranscriptSchema, t.id)
                row.summary = summary

        return t.id

    def _add_refined_item(self, item_type: WorkItemType, text: str) -> WorkItem:
        """Create a refined WorkItem with its TranscriptEvent."""
        self._minute += 1
        wi = WorkItem(
            transcript_id=self.transcript_id,
            item_type=item_type,
            event_ids=[self._minute],  # placeholder event IDs
            processed=WorkItemStage.REFINED,
            created_at=_ts(self._minute),
        )
        with self.db.session() as session:
            wi = wi.save(session)

        te = TranscriptEvent(
            transcript_id=self.transcript_id,
            work_item_id=wi.id,
            event_type=item_type,
            text=text,
            created_at=_ts(self._minute),
        )
        with self.db.session() as session:
            te.save(session)

        return wi

    def add_prompt(self, text: str = "help me implement JWT authentication for the entire API system") -> WorkItem:
        return self._add_refined_item(WorkItemType.PROMPT, text)

    def add_thinking(self, text: str = "Thinking: JWT vs sessions → JWT chosen") -> WorkItem:
        return self._add_refined_item(WorkItemType.THINKING, text)

    def add_tool_pair(self, text: str = "Read: auth.py → found JWT class") -> WorkItem:
        return self._add_refined_item(WorkItemType.TOOL_PAIR, text)

    def add_response(self, text: str = "I found the authentication module and here's what I see") -> WorkItem:
        return self._add_refined_item(WorkItemType.RESPONSE, text)


class TestExtraction:
    @patch("observer.pipeline.extraction.summarize_transcript")
    @patch("observer.pipeline.extraction.extract_artifacts")
    def test_extracts_artifacts_from_refined_items(self, mock_extract, mock_summarize, db):
        mock_extract.return_value = ExtractionResult(
            artifacts=[
                ExtractedArtifact(
                    artifact_type="knowledge",
                    text="JWT uses RS256",
                    source="RS256 algorithm",
                )
            ]
        )
        mock_summarize.return_value = "## Title\nJWT Auth\n## Goal\nImplement JWT"

        s = _Setup(db)
        s.create_transcript()
        s.add_prompt()
        s.add_response("JWT uses RS256 algorithm for signing tokens in production systems")

        total = WorkItemExtractor.extract_batch(db)
        assert total == 1

        with db.session() as session:
            knowledge = session.query(ArtifactSchema).filter_by(artifact_type="knowledge").all()
            assert len(knowledge) == 1
            assert knowledge[0].text == "JWT uses RS256"
            assert knowledge[0].transcript_event_id is not None
            assert knowledge[0].prompt_event_id is not None

    @patch("observer.pipeline.extraction.summarize_transcript")
    def test_prompt_only_skips_extraction(self, mock_summarize, db):
        """When only prompts are present, extraction is skipped entirely."""
        mock_summarize.return_value = "summary"

        s = _Setup(db)
        s.create_transcript()
        s.add_prompt()

        WorkItemExtractor.extract_batch(db)

        mock_summarize.assert_called_once()

    @patch("observer.pipeline.extraction.summarize_transcript")
    @patch("observer.pipeline.extraction.extract_artifacts")
    def test_extraction_receives_summary_context(self, mock_extract, mock_summarize, db):
        mock_extract.return_value = ExtractionResult()
        mock_summarize.return_value = "summary"

        s = _Setup(db)
        s.create_transcript(summary="Previous session context")
        s.add_prompt("check the config settings in the backend system please now")
        s.add_tool_pair("Read: config.py → found settings")
        s.add_response("I found the config settings for the backend system just now")

        WorkItemExtractor.extract_batch(db)

        summary_arg = mock_extract.call_args[0][0]
        assert summary_arg == "Previous session context"

    @patch("observer.pipeline.extraction.summarize_transcript")
    @patch("observer.pipeline.extraction.extract_artifacts")
    def test_extraction_receives_transcript_event_texts(self, mock_extract, mock_summarize, db):
        mock_extract.return_value = ExtractionResult()
        mock_summarize.return_value = "summary"

        s = _Setup(db)
        s.create_transcript()
        s.add_prompt()
        s.add_tool_pair("Read: auth.py → found JWT class")
        s.add_response("I found the authentication module and here is what I see now")

        WorkItemExtractor.extract_batch(db)

        events_arg = mock_extract.call_args[0][1]
        assert any("auth.py" in e for e in events_arg)

    @patch("observer.pipeline.extraction.summarize_transcript")
    @patch("observer.pipeline.extraction.extract_artifacts")
    def test_extraction_failure_marks_error(self, mock_extract, mock_summarize, db):
        """Extraction failure marks items as ERROR and skips summary."""
        mock_extract.side_effect = ExtractionError("LLM failed")

        s = _Setup(db)
        s.create_transcript()
        s.add_prompt()
        wi = s.add_response("I will help you with the entire authentication system now")

        WorkItemExtractor.extract_batch(db)

        updated = WorkItem.get(wi.id)
        assert updated.processed == WorkItemStage.ERROR
        mock_summarize.assert_not_called()


class TestSummarization:
    @patch("observer.pipeline.extraction.summarize_transcript")
    @patch("observer.pipeline.extraction.extract_artifacts")
    def test_updates_transcript_summary_and_title(self, mock_extract, mock_summarize, db):
        mock_extract.return_value = ExtractionResult()
        mock_summarize.return_value = "## Title\nJWT Auth\n## Goal\nImplement JWT auth"

        s = _Setup(db)
        tid = s.create_transcript()
        s.add_prompt()
        s.add_response("I will implement JWT auth for the entire backend API system")

        WorkItemExtractor.extract_batch(db)

        with db.session() as session:
            transcript = session.get(TranscriptSchema, tid)
            assert transcript.summary == "## Title\nJWT Auth\n## Goal\nImplement JWT auth"
            assert transcript.title == "JWT Auth"

    @patch("observer.pipeline.extraction.summarize_transcript")
    @patch("observer.pipeline.extraction.extract_artifacts")
    def test_summarize_receives_all_events(self, mock_extract, mock_summarize, db):
        mock_extract.return_value = ExtractionResult()
        mock_summarize.return_value = "## Title\nUpdated"

        s = _Setup(db)
        s.create_transcript()
        s.add_prompt("first task for the backend API system please now first")
        s.add_prompt("second task for the backend API system please now second")
        s.add_response("I will handle the second task for the backend system now")

        WorkItemExtractor.extract_batch(db)

        events_arg = mock_summarize.call_args[0][0]
        assert len(events_arg) == 3  # prompt1 + prompt2 + response

    @patch("observer.pipeline.extraction.summarize_transcript")
    @patch("observer.pipeline.extraction.extract_artifacts")
    def test_summarize_failure_preserves_extraction(self, mock_extract, mock_summarize, db):
        mock_extract.return_value = ExtractionResult(
            artifacts=[
                ExtractedArtifact(
                    artifact_type="knowledge",
                    text="important fact",
                    source="source",
                )
            ]
        )
        mock_summarize.side_effect = ExtractionError("LLM failed")

        s = _Setup(db)
        tid = s.create_transcript()
        s.add_prompt()
        s.add_response("I found an important technical fact about the system now")

        WorkItemExtractor.extract_batch(db)

        # Artifacts were created (extraction succeeded)
        with db.session() as session:
            artifacts = session.query(ArtifactSchema).filter_by(artifact_type="knowledge").all()
            assert len(artifacts) == 1

        # Summary not updated (summarization failed)
        with db.session() as session:
            transcript = session.get(TranscriptSchema, tid)
            assert transcript.summary is None


class TestTerminalMarking:
    @patch("observer.pipeline.extraction.summarize_transcript")
    @patch("observer.pipeline.extraction.extract_artifacts")
    def test_marks_all_items_terminal(self, mock_extract, mock_summarize, db):
        mock_extract.return_value = ExtractionResult()
        mock_summarize.return_value = "summary"

        s = _Setup(db)
        s.create_transcript()
        wi_prompt = s.add_prompt()
        wi_response = s.add_response("I found the auth module in the codebase now")

        WorkItemExtractor.extract_batch(db)

        assert WorkItem.get(wi_prompt.id).processed == WorkItemStage.TERMINAL
        assert WorkItem.get(wi_response.id).processed == WorkItemStage.TERMINAL

    @patch("observer.pipeline.extraction.summarize_transcript")
    @patch("observer.pipeline.extraction.extract_artifacts")
    def test_prompt_event_id_linked_to_extracted_artifacts(self, mock_extract, mock_summarize, db):
        mock_extract.return_value = ExtractionResult(
            artifacts=[
                ExtractedArtifact(
                    artifact_type="knowledge",
                    text="Auth uses JWT",
                    source="found JWT",
                )
            ]
        )
        mock_summarize.return_value = "summary"

        s = _Setup(db)
        s.create_transcript()
        s.add_prompt("implement JWT auth for the backend API system please now")
        s.add_response("I have implemented JWT auth in the backend API system now")

        WorkItemExtractor.extract_batch(db)

        with db.session() as session:
            # The prompt's TranscriptEvent provides the prompt_event_id linkage
            prompt_te = (
                session.query(TranscriptEventSchema)
                .filter_by(event_type=WorkItemType.PROMPT.value)
                .first()
            )
            knowledge_artifact = (
                session.query(ArtifactSchema).filter_by(artifact_type="knowledge").first()
            )

            assert prompt_te is not None
            assert knowledge_artifact.prompt_event_id == prompt_te.id


class TestMultipleTranscripts:
    @patch("observer.pipeline.extraction.summarize_transcript")
    @patch("observer.pipeline.extraction.extract_artifacts")
    def test_isolated_processing(self, mock_extract, mock_summarize, db):
        mock_extract.return_value = ExtractionResult()
        mock_summarize.return_value = "summary"

        # Create two separate transcripts
        s1 = _Setup(db)
        with db.session() as session:
            p = Project(name="proj1", repo_path="/repo1").save(session)
            t1 = Transcript(project_id=p.id, session_id="s1", path="/t1.jsonl", started_at=NOW).save(session)
        s1.transcript_id = t1.id

        s2 = _Setup(db)
        with db.session() as session:
            p2 = Project(name="proj2", repo_path="/repo2").save(session)
            t2 = Transcript(project_id=p2.id, session_id="s2", path="/t2.jsonl", started_at=NOW).save(session)
        s2.transcript_id = t2.id

        s1.add_prompt("help with auth in project one right now please auth")
        s1.add_response("I will work on auth for project one backend system now")
        s2.add_prompt("help with routes in project two right now please routes")
        s2.add_response("I will work on routes for project two backend system now")

        WorkItemExtractor.extract_batch(db)

        # Both transcripts processed independently
        assert not WorkItem.has_by_processed(WorkItemStage.REFINED)  # all moved to terminal


class TestBatchEdgeCases:
    def test_empty_batch(self, db):
        total = WorkItemExtractor.extract_batch(db)
        assert total == 0

    def test_has_pending_false_when_empty(self, db):  # noqa: ARG002
        assert WorkItemExtractor.has_pending() is False

    def test_has_pending_true_with_refined_items(self, db):
        s = _Setup(db)
        s.create_transcript()
        s.add_prompt()

        assert WorkItemExtractor.has_pending() is True

    def test_has_pending_false_for_unprocessed_items(self, db):
        """Items at UNREFINED stage are not pending for processing."""
        s = _Setup(db)
        s.create_transcript()
        wi = WorkItem(
            transcript_id=s.transcript_id,
            item_type=WorkItemType.PROMPT,
            event_ids=[1],
            created_at=NOW,
        )
        with db.session() as session:
            wi.save(session)

        assert WorkItemExtractor.has_pending() is False

    @patch("observer.pipeline.extraction.summarize_transcript")
    @patch("observer.pipeline.extraction.extract_artifacts")
    def test_batch_limit(self, mock_extract, mock_summarize, db):
        mock_extract.return_value = ExtractionResult()
        mock_summarize.return_value = "summary"

        s = _Setup(db)
        s.create_transcript()
        for _ in range(5):
            s.add_prompt("help me implement JWT authentication for the entire API system")
            s.add_response("I will help you with the entire authentication system now")

        # Process with batch limit of 4 — should only process first 4 work items
        WorkItemExtractor.extract_batch(db, batch_limit=4)

        remaining = WorkItem.get_by_processed(WorkItemStage.REFINED, limit=100)
        assert len(remaining) == 6  # 10 total - 4 processed = 6 remaining
