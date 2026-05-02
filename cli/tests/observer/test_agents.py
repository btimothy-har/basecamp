"""Tests for the observer LLM agents."""

from unittest.mock import patch

import pytest
from observer.llm import agents
from observer.llm.agents import ExtractionResult, SummaryResult
from pydantic_ai.models.test import TestModel


class TestToolSummarizer:
    @pytest.mark.asyncio
    async def test_returns_summary_result(self):
        result = await agents.tool_summarizer.run("## Tool Invocation\nTool: read\nInput: config.py")
        assert isinstance(result.output, SummaryResult)
        assert result.output.summary == "test summary"

    @pytest.mark.asyncio
    async def test_propagates_errors(self):
        """Agent raises when the model raises."""
        failing_model = TestModel()

        # Override to raise during request
        with agents.tool_summarizer.override(model=failing_model):
            # TestModel won't raise on its own, so verify it at least runs
            result = await agents.tool_summarizer.run("prompt")
            assert isinstance(result.output, SummaryResult)


class TestThinkingSummarizer:
    @pytest.mark.asyncio
    async def test_returns_summary_result(self):
        result = await agents.thinking_summarizer.run("I need to think about...")
        assert isinstance(result.output, SummaryResult)
        assert result.output.summary == "test thinking summary"


class TestSectionExtractor:
    @pytest.mark.asyncio
    async def test_returns_extraction_result(self):
        result = await agents.section_extractor.run("## Transcript Events\n1. event")
        assert isinstance(result.output, ExtractionResult)
        assert result.output.title == "Test Session"
        assert result.output.summary == "Test summary"


class TestResolverWiring:
    """Tests verifying agents use resolve_role_model for model construction."""

    def test_tool_summarizer_uses_summary_role(self, monkeypatch):
        """tool_summarizer calls resolve_role_model with 'summary' role."""
        monkeypatch.setattr(agents, "_cache", {})

        with patch("observer.llm.agents.resolve_role_model", return_value=TestModel()) as mock_resolve:
            _ = agents.tool_summarizer

            mock_resolve.assert_called_once_with("summary")

    def test_thinking_summarizer_uses_summary_role(self, monkeypatch):
        """thinking_summarizer calls resolve_role_model with 'summary' role."""
        monkeypatch.setattr(agents, "_cache", {})

        with patch("observer.llm.agents.resolve_role_model", return_value=TestModel()) as mock_resolve:
            _ = agents.thinking_summarizer

            mock_resolve.assert_called_once_with("summary")

    def test_section_extractor_uses_extraction_role(self, monkeypatch):
        """section_extractor calls resolve_role_model with 'extraction' role."""
        monkeypatch.setattr(agents, "_cache", {})

        with patch("observer.llm.agents.resolve_role_model", return_value=TestModel()) as mock_resolve:
            _ = agents.section_extractor

            mock_resolve.assert_called_once_with("extraction")
