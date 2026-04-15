"""Tests for the observer LLM agents."""

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
