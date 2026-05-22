"""Core protocol and context contracts for infra job runners."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pi_memory.db.database import Database
from pi_memory.db.schema import Job
from pi_memory.infra.job_queue.store import JobStore


class BaseJob(Protocol):
    """Minimal contract for a runnable job."""

    kind: str

    def run(self, context: JobExecutionContext, job: Job) -> dict[str, Any]:
        """Run a job using shared infra context."""
        ...


@dataclass(frozen=True)
class JobExecutionContext:
    """Shared context available to infra jobs.

    Keep this intentionally small so it stays decoupled from domain-specific workflows.
    """

    database: Database
    store: JobStore
