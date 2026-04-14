"""LLM functions for the extraction pipeline.

Stateless prompt composition + pydantic-ai extraction. Each function
builds a prompt, calls the LLM via ``extract_structured``, and returns
a typed result. All functions are async.
"""

import logging

from observer import prompts
from observer.pipeline.models import ExtractionResult, SummaryResult
from observer.services.agent import extract_structured
from observer.services.config import get_extraction_model, get_summary_model

logger = logging.getLogger(__name__)


async def summarize_tool_pair(
    tool_name: str,
    tool_input: str,
    result_content: str,
) -> SummaryResult:
    """Summarize one tool_use + tool_result pair."""
    prompt = f"## Tool Invocation\nTool: {tool_name}\nInput: {tool_input}\n\n## Result\n{result_content}"

    try:
        return await extract_structured(
            model=get_summary_model(),
            system_prompt=prompts.tool_summarize,
            user_prompt=prompt,
            output_type=SummaryResult,
        )
    except Exception:
        logger.warning("Tool summary failed for %s, using fallback", tool_name, exc_info=True)
        return SummaryResult(summary=f"{tool_name}: {tool_input}")


async def summarize_thinking(thinking_text: str) -> str:
    """Summarize a thinking block for the context buffer."""
    try:
        result = await extract_structured(
            model=get_summary_model(),
            system_prompt=prompts.thinking_summarize,
            user_prompt=thinking_text,
            output_type=SummaryResult,
        )
    except Exception:
        logger.warning("Thinking summary failed, using fallback", exc_info=True)
        return f"Thinking: {thinking_text}"
    else:
        return result.summary


async def extract_sections(events: list[str]) -> ExtractionResult:
    """Extract structured sections from all transcript events."""
    event_list = "\n".join(f"{i + 1}. {e}" for i, e in enumerate(events))
    prompt = f"## Transcript Events\n{event_list}"

    try:
        return await extract_structured(
            model=get_extraction_model(),
            system_prompt=prompts.extract,
            user_prompt=prompt,
            output_type=ExtractionResult,
        )
    except Exception:
        logger.warning("Extraction failed, returning fallback", exc_info=True)
        return ExtractionResult(
            title="Untitled session",
            summary="",
            knowledge="",
            decisions="",
            constraints="",
            actions="",
        )
