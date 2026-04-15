"""Tests for the TranscriptExtractor pipeline."""

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from observer.data.enums import SectionType, WorkItemType
from observer.llm import agents
from observer.llm.agents import ExtractionResult
from observer.pipeline.extraction import TranscriptExtractor
from pydantic_ai.models.test import TestModel

NOW = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)

_FULL_RESULT = ExtractionResult(
    title="JWT Auth",
    summary="Implemented JWT authentication",
    knowledge="JWT uses RS256 for signing",
    decisions="Chose JWT over sessions",
    constraints="Tokens expire in 24h",
    actions="Updated auth.py",
)


def _make_event(text: str, event_type: WorkItemType) -> MagicMock:
    event = MagicMock()
    event.text = text
    event.event_type = event_type
    return event


def _make_db() -> MagicMock:
    return MagicMock()


@contextmanager
def _override_extractor(result: ExtractionResult = _FULL_RESULT):
    """Override section_extractor to return a specific ExtractionResult."""
    model = TestModel(custom_output_args=result.model_dump())
    with agents.section_extractor.override(model=model):
        yield


class TestTranscriptExtractor:
    @patch("observer.pipeline.extraction.Artifact")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_happy_path_returns_five_sections(self, mock_get, mock_extraction):
        """All 5 sections populated → returns 5, each section saved."""
        mock_get.return_value = [
            _make_event("help me implement JWT auth", WorkItemType.PROMPT),
            _make_event("I found the auth module", WorkItemType.RESPONSE),
        ]

        with _override_extractor():
            count = TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        assert count == 5
        assert mock_extraction.call_count == 5

    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_empty_events_returns_zero(self, mock_get):
        """No events → returns 0, section_extractor not called."""
        mock_get.return_value = []

        count = TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        assert count == 0

    @patch("observer.pipeline.extraction.Artifact")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_thinking_events_filtered_out(self, mock_get, _mock_extraction):
        """THINKING events are excluded from text passed to section_extractor."""
        mock_get.return_value = [
            _make_event("thinking about JWT vs sessions", WorkItemType.THINKING),
            _make_event("user asked for JWT auth", WorkItemType.PROMPT),
        ]

        # Use a custom TestModel so we can inspect what was passed
        calls = []
        original_run = agents.section_extractor.run

        async def capture_run(prompt, *args, **kwargs):
            calls.append(prompt)
            return await original_run(prompt, *args, **kwargs)

        with _override_extractor():
            agents.section_extractor.run = capture_run
            try:
                TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)
            finally:
                agents.section_extractor.run = original_run

        assert len(calls) == 1
        assert "thinking about JWT vs sessions" not in calls[0]
        assert "user asked for JWT auth" in calls[0]

    @patch("observer.pipeline.extraction.Artifact")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_skipped_event_types_filtered(self, mock_get, _mock_extraction):
        """TASK_MANAGEMENT (is_skipped=True) events are excluded."""
        mock_get.return_value = [
            _make_event("TaskCreate called", WorkItemType.TASK_MANAGEMENT),
            _make_event("I found the auth module", WorkItemType.RESPONSE),
        ]

        calls = []
        original_run = agents.section_extractor.run

        async def capture_run(prompt, *args, **kwargs):
            calls.append(prompt)
            return await original_run(prompt, *args, **kwargs)

        with _override_extractor():
            agents.section_extractor.run = capture_run
            try:
                TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)
            finally:
                agents.section_extractor.run = original_run

        assert len(calls) == 1
        assert "TaskCreate called" not in calls[0]
        assert "I found the auth module" in calls[0]

    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_extraction_error_returns_zero(self, mock_get):
        """Exception from LLM → returns 0 (fallback has empty sections)."""
        mock_get.return_value = [
            _make_event("help with auth", WorkItemType.PROMPT),
        ]

        with patch.object(agents.section_extractor, "run", new=AsyncMock(side_effect=RuntimeError("LLM failed"))):
            count = TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        assert count == 0

    @patch("observer.pipeline.extraction.Artifact")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_summary_title_prepended(self, mock_get, mock_extraction):
        """Summary section text is prefixed with '## {title}'."""
        mock_get.return_value = [
            _make_event("help with auth", WorkItemType.PROMPT),
        ]

        with _override_extractor():
            TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        summary_call = next(
            c for c in mock_extraction.call_args_list if c.kwargs.get("section_type") == SectionType.SUMMARY
        )
        expected_text = f"## {_FULL_RESULT.title}\n{_FULL_RESULT.summary}"
        assert summary_call.kwargs["text"] == expected_text

    @patch("observer.pipeline.extraction.Artifact")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_empty_section_fields_skipped(self, mock_get, mock_extraction):
        """Sections with empty text are not saved → count = 3."""
        mock_get.return_value = [
            _make_event("help with auth", WorkItemType.PROMPT),
        ]

        partial = ExtractionResult(
            title="JWT Auth",
            summary="Implemented JWT",
            knowledge="",
            decisions="",
            constraints="tokens expire in 24h",
            actions="updated auth.py",
        )

        with _override_extractor(partial):
            count = TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        assert count == 3
        assert mock_extraction.call_count == 3

    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_all_events_filtered_returns_zero(self, mock_get):
        """All events are thinking or skipped → returns 0, section_extractor not called."""
        mock_get.return_value = [
            _make_event("thinking about JWT", WorkItemType.THINKING),
            _make_event("TaskCreate called", WorkItemType.TASK_MANAGEMENT),
        ]

        count = TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        assert count == 0
