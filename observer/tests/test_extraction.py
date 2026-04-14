"""Tests for the TranscriptExtractor pipeline."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from observer.data.enums import SectionType, WorkItemType
from observer.pipeline.extraction import TranscriptExtractor
from observer.pipeline.models import ExtractionResult

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


def _mock_extractor(return_value=_FULL_RESULT):
    """Patch section_extractor.run to return a given ExtractionResult."""
    mock_result = AsyncMock()
    mock_result.output = return_value
    return patch(
        "observer.services.agents.section_extractor",
        **{"run": AsyncMock(return_value=mock_result)},
    )


class TestTranscriptExtractor:
    @patch("observer.pipeline.extraction.Artifact")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_happy_path_returns_five_sections(self, mock_get, mock_extraction):
        """All 5 sections populated → returns 5, each section saved."""
        mock_get.return_value = [
            _make_event("help me implement JWT auth", WorkItemType.PROMPT),
            _make_event("I found the auth module", WorkItemType.RESPONSE),
        ]

        with _mock_extractor():
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

        mock_result = AsyncMock()
        mock_result.output = _FULL_RESULT
        mock_run = AsyncMock(return_value=mock_result)

        with patch("observer.services.agents.section_extractor") as mock_agent:
            mock_agent.run = mock_run
            TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        prompt = mock_run.call_args[0][0]
        assert "thinking about JWT vs sessions" not in prompt
        assert "user asked for JWT auth" in prompt

    @patch("observer.pipeline.extraction.Artifact")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_skipped_event_types_filtered(self, mock_get, _mock_extraction):
        """TASK_MANAGEMENT (is_skipped=True) events are excluded."""
        mock_get.return_value = [
            _make_event("TaskCreate called", WorkItemType.TASK_MANAGEMENT),
            _make_event("I found the auth module", WorkItemType.RESPONSE),
        ]

        mock_result = AsyncMock()
        mock_result.output = _FULL_RESULT
        mock_run = AsyncMock(return_value=mock_result)

        with patch("observer.services.agents.section_extractor") as mock_agent:
            mock_agent.run = mock_run
            TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        prompt = mock_run.call_args[0][0]
        assert "TaskCreate called" not in prompt
        assert "I found the auth module" in prompt

    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_extraction_error_returns_zero(self, mock_get):
        """Exception from LLM → returns 0 (fallback has empty sections)."""
        mock_get.return_value = [
            _make_event("help with auth", WorkItemType.PROMPT),
        ]

        with patch("observer.services.agents.section_extractor") as mock_agent:
            mock_agent.run = AsyncMock(side_effect=RuntimeError("LLM failed"))
            count = TranscriptExtractor.extract_transcript(_make_db(), transcript_id=1)

        assert count == 0

    @patch("observer.pipeline.extraction.Artifact")
    @patch("observer.pipeline.extraction.TranscriptEvent.get_for_transcript")
    def test_summary_title_prepended(self, mock_get, mock_extraction):
        """Summary section text is prefixed with '## {title}'."""
        mock_get.return_value = [
            _make_event("help with auth", WorkItemType.PROMPT),
        ]

        with _mock_extractor():
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

        with _mock_extractor(partial):
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
