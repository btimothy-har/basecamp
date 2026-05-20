"""Factory for configured durable-memory candidate evaluators."""

from __future__ import annotations

from pi_memory.durable.evaluator import CandidateEvaluator, PydanticAICandidateEvaluator
from pi_memory.settings import Settings, settings


def create_candidate_evaluator(memory_settings: Settings | None = None) -> CandidateEvaluator:
    """Create the configured PydanticAI durable-memory candidate evaluator.

    Args:
        memory_settings: Optional settings source. Defaults to the process-wide
            pi-memory settings, including environment overrides.

    Returns:
        Configured PydanticAI candidate evaluator.

    Raises:
        MissingInterpretationModelError: If no quality, tool-summary, or
            interpretation model is configured.
    """
    effective_settings = settings if memory_settings is None else memory_settings
    return PydanticAICandidateEvaluator(effective_settings.require_quality_model())
