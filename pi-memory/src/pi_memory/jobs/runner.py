"""Minimal pi-memory job runner."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from pi_memory.db import JOB_KIND_PROCESS_TRANSCRIPT, Database, Job, Transcript, TranscriptEntry, database
from pi_memory.jobs.store import JobStore

EXPECTED_OBJECT_PAYLOAD_ERROR = "expected object payload"
TRANSCRIPT_ID_INTEGER_ERROR = "transcript_id must be an integer"


class JobRunnerError(RuntimeError):
    """Base class for job runner errors."""


class PermanentJobError(JobRunnerError):
    """Raised when malformed job data cannot be fixed by retrying."""


class UnsupportedJobKindError(PermanentJobError):
    """Raised when the runner does not support a job kind."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"Unsupported job kind: {kind}")


class InvalidJobPayloadError(PermanentJobError):
    """Raised when a job payload is missing required fields or has invalid values."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Invalid job payload: {message}")


class TranscriptNotFoundError(PermanentJobError):
    """Raised when a process_transcript job references a missing transcript."""

    def __init__(self, transcript_id: int) -> None:
        super().__init__(f"Transcript {transcript_id} was not found")


class JobRunner:
    """Run a claimed durable job to completion or recorded failure."""

    def __init__(self, database: Database = database) -> None:
        self._database = database
        self._store = JobStore(database=database)

    def run(
        self,
        job_id: int,
        run_id: str,
        *,
        running_pid: int | None = None,
        now: datetime | None = None,
    ) -> Job:
        """Start, dispatch, and finish a claimed job."""
        job = self._store.start(
            job_id,
            run_id,
            running_pid=os.getpid() if running_pid is None else running_pid,
            now=now,
        )

        try:
            result_json = self._dispatch(job)
        except PermanentJobError as error:
            self._store.fail(job_id, run_id, error=str(error), exit_code=1, retry=False, now=now)
            raise
        except Exception as error:
            self._store.fail(job_id, run_id, error=str(error), exit_code=1, retry=True, now=now)
            raise

        return self._store.complete(job_id, run_id, result_json=result_json, exit_code=0, now=now)

    def _dispatch(self, job: Job) -> dict[str, Any]:
        if job.kind == JOB_KIND_PROCESS_TRANSCRIPT:
            return self._process_transcript(job)
        raise UnsupportedJobKindError(job.kind)

    def _process_transcript(self, job: Job) -> dict[str, Any]:
        transcript_id = _payload_transcript_id(job.payload_json)
        self._database.initialize()
        with self._database.session() as session:
            transcript = session.get(Transcript, transcript_id)
            if transcript is None:
                raise TranscriptNotFoundError(transcript_id)

            entry_count = session.scalar(
                select(func.count()).select_from(TranscriptEntry).where(TranscriptEntry.transcript_id == transcript_id),
            )
            return {
                "transcript_id": transcript.id,
                "session_id": transcript.session.session_id,
                "entry_count": entry_count,
                "cursor_offset": transcript.cursor_offset,
                "file_size": transcript.file_size,
            }


def _payload_transcript_id(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise InvalidJobPayloadError(EXPECTED_OBJECT_PAYLOAD_ERROR)

    transcript_id = payload.get("transcript_id")
    if not isinstance(transcript_id, int) or isinstance(transcript_id, bool):
        raise InvalidJobPayloadError(TRANSCRIPT_ID_INTEGER_ERROR)
    return transcript_id
