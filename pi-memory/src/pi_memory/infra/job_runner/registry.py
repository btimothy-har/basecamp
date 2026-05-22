"""Simple in-memory registry for infra jobs."""

from __future__ import annotations

from collections.abc import Iterable

from .base import BaseJob
from .errors import UnsupportedJobKindError


class JobRegistry:
    """Map job kind strings to runnable `BaseJob` implementations."""

    def __init__(self, jobs: Iterable[BaseJob] | None = None) -> None:
        self._jobs: dict[str, BaseJob] = {}
        if jobs is not None:
            self.register_many(jobs)

    def register(self, job: BaseJob) -> None:
        """Register a single job instance."""
        self._jobs[job.kind] = job

    def register_many(self, jobs: Iterable[BaseJob]) -> None:
        """Register multiple job instances."""
        for job in jobs:
            self.register(job)

    def get(self, kind: str) -> BaseJob:
        """Return the job implementation for *kind*.

        Raises:
            UnsupportedJobKindError: when no registration exists for *kind*.
        """
        if kind not in self._jobs:
            raise UnsupportedJobKindError(kind)

        return self._jobs[kind]

    def __contains__(self, kind: str) -> bool:
        """Return whether a kind is registered."""
        return kind in self._jobs
