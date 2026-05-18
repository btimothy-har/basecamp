"""Factory for configured session interpreters."""

from __future__ import annotations

from pi_memory.interpretation.interpreter import (
    PydanticAISessionInterpreter,
    PydanticAIToolActivitySummarizer,
    SessionInterpreter,
    ToolActivitySummarizer,
)
from pi_memory.settings import Settings, settings


def create_session_interpreter(memory_settings: Settings | None = None) -> SessionInterpreter:
    """Create the configured PydanticAI session interpreter.

    Args:
        memory_settings: Optional settings source. Defaults to the process-wide
            pi-memory settings, including environment overrides.

    Returns:
        Configured PydanticAI session interpreter.

    Raises:
        MissingInterpretationModelError: If no interpretation model is configured.
        PydanticAIDependencyError: If pydantic-ai is unavailable.
    """
    effective_settings = settings if memory_settings is None else memory_settings
    return PydanticAISessionInterpreter(effective_settings.require_interpretation_model())


def create_tool_activity_summarizer(memory_settings: Settings | None = None) -> ToolActivitySummarizer:
    """Create the configured PydanticAI tool activity summarizer.

    Args:
        memory_settings: Optional settings source. Defaults to the process-wide
            pi-memory settings, including environment overrides.

    Returns:
        Configured PydanticAI tool activity summarizer.

    Raises:
        MissingInterpretationModelError: If no interpretation model is configured.
        PydanticAIDependencyError: If pydantic-ai is unavailable.
    """
    effective_settings = settings if memory_settings is None else memory_settings
    return PydanticAIToolActivitySummarizer(effective_settings.require_tool_summary_model())
