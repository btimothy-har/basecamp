"""Tests for the observer LLM agents."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from observer.llm.models import ExtractionResult, SummaryResult


class TestToolSummarizer:
    @pytest.mark.asyncio
    async def test_returns_summary_result(self):
        mock_result = MagicMock()
        mock_result.output = SummaryResult(summary="Read file config.py")

        with patch("observer.llm.agents.tool_summarizer") as mock_agent:
            mock_agent.run = AsyncMock(return_value=mock_result)
            result = await mock_agent.run("## Tool Invocation\nTool: read\nInput: config.py")
            assert result.output.summary == "Read file config.py"

    @pytest.mark.asyncio
    async def test_propagates_errors(self):
        with patch("observer.llm.agents.tool_summarizer") as mock_agent:
            mock_agent.run = AsyncMock(side_effect=RuntimeError("API error"))
            with pytest.raises(RuntimeError, match="API error"):
                await mock_agent.run("prompt")


class TestThinkingSummarizer:
    @pytest.mark.asyncio
    async def test_returns_summary_result(self):
        mock_result = MagicMock()
        mock_result.output = SummaryResult(summary="Considering approach")

        with patch("observer.llm.agents.thinking_summarizer") as mock_agent:
            mock_agent.run = AsyncMock(return_value=mock_result)
            result = await mock_agent.run("I need to think about...")
            assert result.output.summary == "Considering approach"


class TestSectionExtractor:
    @pytest.mark.asyncio
    async def test_returns_extraction_result(self):
        expected = ExtractionResult(
            title="Test Session",
            summary="Did stuff",
            knowledge="Learned things",
            decisions="Decided stuff",
            constraints="Some limits",
            actions="TODO items",
        )
        mock_result = MagicMock()
        mock_result.output = expected

        with patch("observer.llm.agents.section_extractor") as mock_agent:
            mock_agent.run = AsyncMock(return_value=mock_result)
            result = await mock_agent.run("## Transcript Events\n1. event")
            assert result.output.title == "Test Session"
            assert result.output.summary == "Did stuff"
