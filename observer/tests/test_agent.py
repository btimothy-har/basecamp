"""Tests for the pydantic-ai based LLM agent."""

from unittest.mock import AsyncMock, patch

import pytest
from observer.exceptions import ExtractionError
from observer.services.agent import extract_structured
from pydantic import BaseModel


class DummyOutput(BaseModel):
    summary: str


class TestExtractStructured:
    @pytest.mark.asyncio
    async def test_returns_parsed_output(self):
        """Successful extraction returns validated pydantic model."""
        mock_result = AsyncMock()
        mock_result.output = DummyOutput(summary="test summary")

        with patch("observer.services.agent.Agent") as mock_agent_cls:
            instance = mock_agent_cls.return_value
            instance.run = AsyncMock(return_value=mock_result)

            result = await extract_structured(
                model="anthropic:claude-3-5-haiku-latest",
                system_prompt="Summarize.",
                user_prompt="Some text to summarize",
                output_type=DummyOutput,
            )

            assert isinstance(result, DummyOutput)
            assert result.summary == "test summary"

            # Verify Agent was created with correct params
            mock_agent_cls.assert_called_once_with(
                "anthropic:claude-3-5-haiku-latest",
                system_prompt="Summarize.",
                output_type=DummyOutput,
            )
            instance.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_extraction_error_on_failure(self):
        """Any exception from pydantic-ai is wrapped in ExtractionError."""
        with patch("observer.services.agent.Agent") as mock_agent_cls:
            instance = mock_agent_cls.return_value
            instance.run = AsyncMock(side_effect=RuntimeError("API connection failed"))

            with pytest.raises(ExtractionError, match="API connection failed"):
                await extract_structured(
                    model="anthropic:claude-3-5-haiku-latest",
                    system_prompt="Summarize.",
                    user_prompt="input",
                    output_type=DummyOutput,
                )

    @pytest.mark.asyncio
    async def test_passes_model_string_through(self):
        """Model string is passed directly to pydantic-ai Agent."""
        mock_result = AsyncMock()
        mock_result.output = DummyOutput(summary="ok")

        with patch("observer.services.agent.Agent") as mock_agent_cls:
            instance = mock_agent_cls.return_value
            instance.run = AsyncMock(return_value=mock_result)

            await extract_structured(
                model="openai:gpt-4o-mini",
                system_prompt="sys",
                user_prompt="input",
                output_type=DummyOutput,
            )

            mock_agent_cls.assert_called_once_with(
                "openai:gpt-4o-mini",
                system_prompt="sys",
                output_type=DummyOutput,
            )
