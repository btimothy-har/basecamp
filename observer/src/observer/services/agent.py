"""LLM agent backed by pydantic-ai.

Provides structured output extraction via pydantic-ai's Agent. Supports
any model provider that pydantic-ai supports (Anthropic, OpenAI, etc.)
through the ``provider:model`` naming convention.

API keys are resolved from environment variables by pydantic-ai's
provider implementations (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.).
"""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent

from observer.exceptions import ExtractionError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


async def extract_structured(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    output_type: type[T],
) -> T:
    """Run a single-turn LLM call and return structured output.

    Args:
        model: pydantic-ai model string (e.g. ``anthropic:claude-3-5-haiku-latest``).
        system_prompt: System prompt for the LLM.
        user_prompt: User message to send.
        output_type: Pydantic model class for structured output.

    Returns:
        Parsed and validated instance of ``output_type``.

    Raises:
        ExtractionError: On any failure (network, validation, timeout).
    """
    agent: Agent[None, T] = Agent(
        model,
        system_prompt=system_prompt,
        output_type=output_type,
    )

    try:
        result = await agent.run(user_prompt)
    except Exception as exc:
        raise ExtractionError(str(exc)) from exc
    else:
        return result.output
