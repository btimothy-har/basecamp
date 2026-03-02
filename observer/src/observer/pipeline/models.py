"""Models for the pipeline.

LLM response models define the structured output shapes returned by
extraction functions. ParsedEvent represents a single parsed
transcript line.
"""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel

from observer.data.enums import ArtifactType


class SummaryResult(BaseModel):
    summary: str


class ExtractedArtifact(BaseModel):
    artifact_type: ArtifactType
    text: str
    source: str


class ExtractionResult(BaseModel):
    artifacts: list[ExtractedArtifact] = []


class ToolSummaryResult(BaseModel):
    summary: str


@dataclass(frozen=True, slots=True)
class ParsedEvent:
    """A single parsed transcript event, ready to become a RawEvent."""

    event_type: str
    timestamp: datetime
    content: str
    message_uuid: str | None
