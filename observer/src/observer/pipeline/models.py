"""Models for the pipeline.

LLM response models define the structured output shapes returned by
extraction functions. ParsedEvent represents a single parsed
transcript line.
"""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel


class SummaryResult(BaseModel):
    summary: str


class ToolSummaryResult(BaseModel):
    summary: str


class TranscriptExtractionResult(BaseModel):
    """Structured extraction result with one field per section type."""

    title: str
    summary: str
    knowledge: str
    decisions: str
    constraints: str
    actions: str


@dataclass(frozen=True, slots=True)
class ParsedEvent:
    """A single parsed transcript event, ready to become a RawEvent."""

    event_type: str
    timestamp: datetime
    content: str
    message_uuid: str | None
