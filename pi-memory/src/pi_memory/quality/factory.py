"""Factory for configured quality assessors."""

from __future__ import annotations

from pi_memory.quality.assessor import PydanticAIQualityAssessor, QualityAssessor
from pi_memory.settings import Settings, settings


def create_quality_assessor(memory_settings: Settings | None = None) -> QualityAssessor:
    """Create the configured PydanticAI quality assessor.

    Args:
        memory_settings: Optional settings source. Defaults to the process-wide
            pi-memory settings, including environment overrides.

    Returns:
        Configured PydanticAI quality assessor.

    Raises:
        MissingInterpretationModelError: If no quality, tool-summary, or
            interpretation model is configured.
    """
    effective_settings = settings if memory_settings is None else memory_settings
    return PydanticAIQualityAssessor(effective_settings.require_quality_model())
