"""Error hierarchy for infra job runner and dispatcher contracts."""

from __future__ import annotations


class JobRunnerError(RuntimeError):
    """Base class for job runner infra errors."""


class PermanentJobError(JobRunnerError):
    """Raised when a job failure should not be retried."""


class UnsupportedJobKindError(PermanentJobError):
    """Raised when a job kind is not registered in a runner registry."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"Unsupported job kind: {kind}")


class JobDispatcherError(RuntimeError):
    """Base class for infra dispatcher errors."""


class ClaimedJobMissingRunIdError(JobDispatcherError):
    """Raised when a claimed job is missing its execution run id."""

    def __init__(self, job_id: int) -> None:
        super().__init__(f"Claimed job {job_id} is missing run_id")
