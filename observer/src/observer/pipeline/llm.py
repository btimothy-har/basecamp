"""LLM functions for the extraction pipeline.

Stateless prompt composition + agent.run + parse. Each function builds
a prompt from structured inputs, calls the LLM, and returns a typed result.
"""

import logging

from observer import prompts
from observer.pipeline.models import (
    ExtractionResult,
    SummaryResult,
    ToolSummaryResult,
)
from observer.services.agent import Agent
from observer.services.config import get_extraction_model

logger = logging.getLogger(__name__)


def summarize_tool_pair(
    tool_name: str,
    tool_input: str,
    result_content: str,
) -> ToolSummaryResult:
    """Summarize one tool_use + tool_result pair."""
    prompt = f"## Tool Invocation\nTool: {tool_name}\nInput: {tool_input}\n\n## Result\n{result_content}"

    agent = Agent(system_prompt=prompts.tool_summarize)
    response = agent.run(prompt, json_schema=ToolSummaryResult.model_json_schema())

    try:
        return ToolSummaryResult.model_validate_json(response.result)
    except Exception:
        logger.warning("Tool summary parse failed for %s, using fallback", tool_name, exc_info=True)
        return ToolSummaryResult(summary=f"{tool_name}: {str(tool_input)}")


def summarize_thinking(thinking_text: str) -> str:
    """Summarize a thinking block for the context buffer."""
    agent = Agent(system_prompt=prompts.thinking_summarize)
    response = agent.run(thinking_text, json_schema=SummaryResult.model_json_schema())

    try:
        result = SummaryResult.model_validate_json(response.result)
    except Exception:
        logger.warning("Thinking summary parse failed, using fallback", exc_info=True)
        return f"Thinking: {thinking_text}"
    else:
        return result.summary


def extract_artifacts(
    summary: str,
    events: list[str],
) -> ExtractionResult:
    """Extract artifacts from a batch of new transcript events."""
    prompt_parts = []
    if summary:
        prompt_parts.append(f"## Current Summary\n{summary}")
    if events:
        event_list = "\n".join(f"- {e}" for e in events)
        prompt_parts.append(f"## New Activity\n{event_list}")

    prompt = "\n\n".join(prompt_parts)
    if not prompt:
        return ExtractionResult()

    agent = Agent(system_prompt=prompts.extract, model=get_extraction_model())
    response = agent.run(prompt, json_schema=ExtractionResult.model_json_schema())

    try:
        return ExtractionResult.model_validate_json(response.result)
    except Exception:
        logger.warning("Failed to parse extraction result, returning empty result", exc_info=True)
        return ExtractionResult()


def summarize_transcript(events: list[str]) -> str:
    """Regenerate transcript summary from ALL transcript events."""
    event_list = "\n".join(f"- {e}" for e in events)
    prompt = f"## Transcript Events\n{event_list}"

    agent = Agent(system_prompt=prompts.summarize)
    response = agent.run(prompt, json_schema=SummaryResult.model_json_schema())

    try:
        result = SummaryResult.model_validate_json(response.result)
    except Exception:
        logger.warning("Summary parse failed, using raw response", exc_info=True)
        return response.result
    else:
        return result.summary
