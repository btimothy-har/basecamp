from __future__ import annotations

import pytest
from pi_memory.db import Job
from pi_memory.infra import job_runner
from pi_memory.infra.job_runner import (
    BaseJob,
    ClaimedJobMissingRunIdError,
    JobDispatcherError,
    JobExecutionContext,
    JobRegistry,
    JobRunnerError,
    PermanentJobError,
    UnsupportedJobKindError,
)


def test_job_registry_get_raises_for_unknown_kind() -> None:
    registry = JobRegistry()

    assert "mystery" not in registry
    with pytest.raises(UnsupportedJobKindError, match="Unsupported job kind: mystery"):
        registry.get("mystery")


class StubJob(BaseJob):
    def __init__(self, kind: str, value: int) -> None:
        self.kind = kind
        self.value = value

    def run(self, _context: JobExecutionContext, _job: Job) -> dict[str, int]:
        return {"value": self.value}


class AnotherStubJob(BaseJob):
    def __init__(self, kind: str, value: int) -> None:
        self.kind = kind
        self.value = value

    def run(self, _context: JobExecutionContext, _job: Job) -> dict[str, int]:
        return {"value": self.value}


def test_job_registry_contains_and_overwrites_duplicates() -> None:
    initial = StubJob("record", 1)
    replacement = AnotherStubJob("record", 2)

    registry = JobRegistry()
    assert ("record" in registry) is False

    registry.register(initial)
    assert "record" in registry
    assert registry.get("record") is initial

    registry.register(replacement)
    assert "record" in registry
    assert registry.get("record") is replacement


def test_infra_job_runner_public_api_exports() -> None:
    expected_exports = {
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
    }

    assert expected_exports <= set(job_runner.__all__)


def test_infra_job_runner_error_hierarchy() -> None:
    assert issubclass(UnsupportedJobKindError, PermanentJobError)
    assert issubclass(PermanentJobError, JobRunnerError)
    assert issubclass(ClaimedJobMissingRunIdError, JobDispatcherError)
