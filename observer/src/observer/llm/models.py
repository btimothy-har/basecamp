"""LLM output schemas.

Pydantic models defining the structured output shapes returned by
each agent.
"""

from pydantic import BaseModel


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
