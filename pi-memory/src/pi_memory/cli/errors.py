"""CLI exception types."""

from __future__ import annotations

import click


class ConflictingInterpretationModelOptionsError(click.UsageError):
    """Raised when mutually exclusive interpretation model options are used."""

    def __init__(self) -> None:
        super().__init__("--clear-interpretation-model cannot be used with --interpretation-model")


class ConflictingToolSummaryModelOptionsError(click.UsageError):
    """Raised when mutually exclusive tool-summary model options are used."""

    def __init__(self) -> None:
        super().__init__("--clear-tool-summary-model cannot be used with --tool-summary-model")


class ConflictingQualityModelOptionsError(click.UsageError):
    """Raised when mutually exclusive quality model options are used."""

    def __init__(self) -> None:
        super().__init__("--clear-quality-model cannot be used with --quality-model")


class ConflictingEmbeddingModelOptionsError(click.UsageError):
    """Raised when mutually exclusive embedding model options are used."""

    def __init__(self) -> None:
        super().__init__("--clear-embedding-model cannot be used with --embedding-model")


class ConflictingToolSummaryConcurrencyOptionsError(click.UsageError):
    """Raised when mutually exclusive tool-summary concurrency options are used."""

    def __init__(self) -> None:
        super().__init__("--clear-tool-summary-concurrency cannot be used with --tool-summary-concurrency")


class JobInspectionNotFoundError(click.ClickException):
    """Raised when the requested inspection job does not exist."""

    def __init__(self, job_id: int) -> None:
        super().__init__(f"Job {job_id} was not found")


class SessionInterpretationInspectionNotFoundError(click.ClickException):
    """Raised when the requested session interpretation snapshot does not exist."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Interpretation snapshot for session {session_id} was not found")


class QualityReportInspectionNotFoundError(click.ClickException):
    """Raised when the requested quality report does not exist."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Quality report for session {session_id} was not found")


class DurableMemoryInspectionNotFoundError(click.ClickException):
    """Raised when the requested durable memory does not exist."""

    def __init__(self, memory_id: int) -> None:
        super().__init__(f"Durable memory {memory_id} was not found")
