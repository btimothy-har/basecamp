"""Tests for the TranscriptExtractor pipeline."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from observer.data.enums import SectionType, WorkItemType
from observer.exceptions import ExtractionError
from observer.pipeline.extraction import TranscriptExtractor
from observer.pipeline.models import TranscriptExtractionResult

NOW = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)

_FULL_RESULT = TranscriptExtractionResult(
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


class TestTranscriptExtractor:
    @patch("observer.pipeline.extraction.TranscriptExtraction")
    @patch("observer.pipeline.extraction.extract_sections")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_happy_path_returns_five_sections(self, mock_get, mock_extract, MockExtraction):
        """All 5 sections populated → returns 5, each section saved."""
        mock_get.return_value = [
            _make_event("help me implement JWT auth", WorkItemType.PROMPT),
            _make_event("I found the auth module", WorkItemType.RESPONSE),
        ]
        mock_extract.return_value = _FULL_RESULT

        count = TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        assert count == 5
        assert MockExtraction.call_count == 5

    @patch("observer.pipeline.extraction.extract_sections")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_empty_events_returns_zero(self, mock_get, mock_extract):
        """No events → returns 0, extract_sections not called."""
        mock_get.return_value = []

        count = TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        assert count == 0
        mock_extract.assert_not_called()

    @patch("observer.pipeline.extraction.TranscriptExtraction")
    @patch("observer.pipeline.extraction.extract_sections")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_thinking_events_filtered_out(self, mock_get, mock_extract, _MockExtraction):
        """THINKING events are excluded from text passed to extract_sections."""
        mock_get.return_value = [
            _make_event("thinking about JWT vs sessions", WorkItemType.THINKING),
            _make_event("user asked for JWT auth", WorkItemType.PROMPT),
        ]
        mock_extract.return_value = _FULL_RESULT

        TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        event_texts = mock_extract.call_args[0][0]
        assert "thinking about JWT vs sessions" not in event_texts
        assert "user asked for JWT auth" in event_texts

    @patch("observer.pipeline.extraction.TranscriptExtraction")
    @patch("observer.pipeline.extraction.extract_sections")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_skipped_event_types_filtered(self, mock_get, mock_extract, _MockExtraction):
        """TASK_MANAGEMENT (is_skipped=True) events are excluded."""
        mock_get.return_value = [
            _make_event("TaskCreate called", WorkItemType.TASK_MANAGEMENT),
            _make_event("I found the auth module", WorkItemType.RESPONSE),
        ]
        mock_extract.return_value = _FULL_RESULT

        TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        event_texts = mock_extract.call_args[0][0]
        assert "TaskCreate called" not in event_texts
        assert "I found the auth module" in event_texts

    @patch("observer.pipeline.extraction.extract_sections")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_extraction_error_returns_zero(self, mock_get, mock_extract):
        """ExtractionError from LLM → returns 0."""
        mock_get.return_value = [
            _make_event("help with auth", WorkItemType.PROMPT),
        ]
        mock_extract.side_effect = ExtractionError("LLM failed")

        count = TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        assert count == 0

    @patch("observer.pipeline.extraction.TranscriptExtraction")
    @patch("observer.pipeline.extraction.extract_sections")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_summary_title_prepended(self, mock_get, mock_extract, MockExtraction):
        """Summary section text is prefixed with '## {title}'."""
        mock_get.return_value = [
            _make_event("help with auth", WorkItemType.PROMPT),
        ]
        mock_extract.return_value = _FULL_RESULT

        TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        summary_call = next(
            c for c in MockExtraction.call_args_list
            if c.kwargs.get("section_type") == SectionType.SUMMARY
        )
        expected_text = f"## {_FULL_RESULT.title}\n{_FULL_RESULT.summary}"
        assert summary_call.kwargs["text"] == expected_text

    @patch("observer.pipeline.extraction.TranscriptExtraction")
    @patch("observer.pipeline.extraction.extract_sections")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_empty_section_fields_skipped(self, mock_get, mock_extract, MockExtraction):
        """Sections with empty text are not saved → count = 3."""
        mock_get.return_value = [
            _make_event("help with auth", WorkItemType.PROMPT),
        ]
        mock_extract.return_value = TranscriptExtractionResult(
            title="JWT Auth",
            summary="Implemented JWT",
            knowledge="",
            decisions="",
            constraints="tokens expire in 24h",
            actions="updated auth.py",
        )

        count = TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        assert count == 3
        assert MockExtraction.call_count == 3

    @patch("observer.pipeline.extraction.extract_sections")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_all_events_filtered_returns_zero(self, mock_get, mock_extract):
        """All events are thinking or skipped → returns 0, extract_sections not called."""
        mock_get.return_value = [
            _make_event("thinking about JWT", WorkItemType.THINKING),
            _make_event("TaskCreate called", WorkItemType.TASK_MANAGEMENT),
        ]

        count = TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        assert count == 0
        mock_extract.assert_not_called()
