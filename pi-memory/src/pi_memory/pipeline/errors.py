"""Pipeline job error hierarchy."""

from __future__ import annotations

from pi_memory.infra.job_runner import JobRunnerError, PermanentJobError
from pi_memory.interpretation import InterpretationValidationError, InterpreterUnavailableError


class InvalidJobPayloadError(PermanentJobError):
    """Raised when a job payload is missing required fields or has invalid values."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Invalid job payload: {message}")


class TranscriptNotFoundError(PermanentJobError):
    """Raised when a job references a missing transcript."""

    def __init__(self, transcript_id: int) -> None:
        super().__init__(f"Transcript {transcript_id} was not found")


class MemoryProjectionJobError(JobRunnerError):
    """Raised when a projection job should be retried safely."""

    def __init__(self) -> None:
        super().__init__("memory projection failed for one or more quality-report claims")


class PermanentInterpretationValidationError(InterpretationValidationError, PermanentJobError):
    """Interpretation validation error that should not be retried."""


class PermanentInterpreterUnavailableError(InterpreterUnavailableError, PermanentJobError):
    """Interpreter unavailable error that should not be retried."""
