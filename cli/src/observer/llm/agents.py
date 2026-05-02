"""LLM agents for the observer pipeline.

Each agent has a fixed system prompt and output type. Agents are
lazy-initialized on first access so config reads happen at call time,
not import time — this avoids failures when the module is imported
in tests or before config is set up.

Usage::

    from observer.llm import agents

    result = await agents.tool_summarizer.run("prompt")

Model refs and provider env vars are resolved by observer.llm.model_resolver.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent

from observer.llm import prompts
from observer.llm.model_resolver import resolve_role_model


class SummaryResult(BaseModel):
    summary: str


class ExtractionResult(BaseModel):
    """Structured extraction result with one field per section type."""

    title: str
    summary: str
    knowledge: str
    decisions: str
    constraints: str
    actions: str


_cache: dict[str, Any] = {}

_AGENTS = {
    "tool_summarizer": lambda: Agent(
        resolve_role_model("summary"),
        system_prompt=prompts.tool_summarize,
        output_type=SummaryResult,
    ),
    "thinking_summarizer": lambda: Agent(
        resolve_role_model("summary"),
        system_prompt=prompts.thinking_summarize,
        output_type=SummaryResult,
    ),
    "section_extractor": lambda: Agent(
        resolve_role_model("extraction"),
        system_prompt=prompts.extract,
        output_type=ExtractionResult,
    ),
}


def __getattr__(name: str) -> Agent:
    """Lazy access: ``agents.tool_summarizer`` etc."""
    if name in _AGENTS:
        if name not in _cache:
            _cache[name] = _AGENTS[name]()
        return _cache[name]
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
