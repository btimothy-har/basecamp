"""Runtime assembly and adapters for memory pipeline stages."""

from __future__ import annotations

import importlib
from typing import Any

from pi_memory.pipeline.runtime.adapters import PipelineAdapters
from pi_memory.pipeline.runtime.errors import (
    InvalidJobPayloadError,
    MemoryProjectionJobError,
    PermanentInterpretationValidationError,
    PermanentInterpreterUnavailableError,
    TranscriptNotFoundError,
)

__all__ = [
    "InvalidJobPayloadError",
    "MemoryProjectionJobError",
    "PermanentInterpretationValidationError",
    "PermanentInterpreterUnavailableError",
    "PipelineAdapters",
    "TranscriptNotFoundError",
    "create_job_registry",
]


def __getattr__(name: str) -> Any:
    if name == "create_job_registry":
        registry = importlib.import_module("pi_memory.pipeline.runtime.registry")
        return registry.create_job_registry
    raise AttributeError(name)
