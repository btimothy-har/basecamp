"""Generic infrastructure job runner for generic job execution."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from pi_memory.db import Database, database
from pi_memory.db.schema import Job
from pi_memory.infra.job_queue.store import JobStore

from .base import BaseJob, JobExecutionContext
from .errors import PermanentJobError
from .registry import JobRegistry


class JobRunner:
    """Run claimed jobs in the generic infrastructure layer."""

    def __init__(
        self,
        database: Database = database,
        store: JobStore | None = None,
        registry: JobRegistry | None = None,
    ) -> None:
        self._database = database
        self._store = JobStore(database=database) if store is None else store
        self._registry = JobRegistry() if registry is None else registry

    def run(
        self,
        job_id: int,
        run_id: str,
        *,
        running_pid: int | None = None,
        now: datetime | None = None,
    ) -> Job:
        """Start, dispatch, and complete or fail a claimed job."""
        job = self._store.start(
            job_id,
            run_id,
            running_pid=os.getpid() if running_pid is None else running_pid,
            now=now,
        )

        try:
            result_json = self._dispatch(job)
        except PermanentJobError as error:
            self._store.fail(
                job_id,
                run_id,
                error=str(error),
                exit_code=1,
                retry=False,
                now=now,
            )
            if error.__cause__ is not None:
                raise error.__cause__ from None
            raise
        except Exception as error:
            self._store.fail(
                job_id,
                run_id,
                error=str(error),
                exit_code=1,
                retry=True,
                now=now,
            )
            raise

        return self._store.complete(
            job_id,
            run_id,
            result_json=result_json,
            exit_code=0,
            now=now,
        )

    def _dispatch(self, job: Job) -> dict[str, Any]:
        job_impl: BaseJob = self._registry.get(job.kind)
        return job_impl.run(JobExecutionContext(database=self._database, store=self._store), job)
