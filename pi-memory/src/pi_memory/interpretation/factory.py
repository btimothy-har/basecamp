"""Factory for configured session interpreters."""

from __future__ import annotations

from typing import cast

from pi_memory.interpretation.interpreter import (
    DeterministicSessionInterpreter,
    PydanticAISessionInterpreter,
    SessionInterpreter,
)
from pi_memory.settings import (
    DEFAULT_INTERPRETER_MODE,
    PYDANTIC_AI_INTERPRETER_MODE,
    Settings,
    settings,
)


def create_session_interpreter(memory_settings: Settings | None = None) -> SessionInterpreter:
    """Create a session interpreter from effective pi-memory settings.

    Args:
        memory_settings: Optional settings source. Defaults to the process-wide
            pi-memory settings, including environment overrides.

    Returns:
        Configured session interpreter.

    Raises:
        SettingsError: If the effective interpreter settings are invalid.
        PydanticAIDependencyError: If pydantic-ai mode is configured but the
            dependency is unavailable.
    """
    effective_settings = settings if memory_settings is None else memory_settings
    configured = effective_settings.as_dict()
    mode = configured["interpreter_mode"]

    if mode == DEFAULT_INTERPRETER_MODE:
        return DeterministicSessionInterpreter()

    if mode == PYDANTIC_AI_INTERPRETER_MODE:
        model = cast(str, configured["interpretation_model"])
        return PydanticAISessionInterpreter(model)

    raise AssertionError
