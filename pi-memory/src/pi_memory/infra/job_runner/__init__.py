"""Infrastructure job runner contracts."""

from .base import BaseJob, JobExecutionContext
from .dispatcher import (
    DEFAULT_COMMAND,
    DEFAULT_LEASE_SECONDS,
    DEFAULT_POLL_INTERVAL_SECONDS,
    ChildProcess,
    Clock,
    JobDispatcher,
    ProcessFactory,
)
from .errors import (
    ClaimedJobMissingRunIdError,
    JobDispatcherError,
    JobRunnerError,
    PermanentJobError,
    UnsupportedJobKindError,
)
from .registry import JobRegistry
from .runner import JobRunner

__all__ = [
    "BaseJob",
    "ChildProcess",
    "ClaimedJobMissingRunIdError",
    "Clock",
    "DEFAULT_COMMAND",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "JobDispatcher",
    "JobDispatcherError",
    "JobExecutionContext",
    "JobRegistry",
    "JobRunner",
    "JobRunnerError",
    "PermanentJobError",
    "ProcessFactory",
    "UnsupportedJobKindError",
]
