"""Enums shared by Pydantic domain models and SQLAlchemy schemas."""

from enum import IntEnum, StrEnum


class RawEventStatus(IntEnum):
    PENDING = 0
    PROCESSED = 1
    SKIPPED = 2
    ERROR = 3


class WorkItemStage(IntEnum):
    UNREFINED = 0
    REFINED = 1
    TERMINAL = 2
    ERROR = 3


class ArtifactType(StrEnum):
    KNOWLEDGE = "knowledge"
    DECISION = "decision"
    ACTION = "action"
    CONSTRAINT = "constraint"


class ArtifactSource(StrEnum):
    EXTRACTED = "extracted"
    MANUAL = "manual"


class WorkItemType(StrEnum):
    PROMPT = "prompt"
    TOOL_PAIR = "tool_pair"
    RESPONSE = "response"
    THINKING = "thinking"
    TASK_MANAGEMENT = "task_management"
    ORPHANED_RESULT = "orphaned_result"
    EMPTY_CONTENT = "empty_content"
    UNRECOGNIZED = "unrecognized"

    @property
    def is_skipped(self) -> bool:
        """Whether this type represents a skipped (non-extractable) event."""
        return self in _SKIP_TYPES


_SKIP_TYPES = frozenset(
    {
        WorkItemType.TASK_MANAGEMENT,
        WorkItemType.ORPHANED_RESULT,
        WorkItemType.EMPTY_CONTENT,
        WorkItemType.UNRECOGNIZED,
    }
)


class SearchSourceType(StrEnum):
    ARTIFACT = "artifact"
    TRANSCRIPT_SUMMARY = "transcript_summary"
