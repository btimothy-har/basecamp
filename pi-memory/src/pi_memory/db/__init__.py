"""Database foundation for pi-memory."""

from pi_memory.db.database import Database, database
from pi_memory.db.schema import (
    JOB_KIND_PROCESS_TRANSCRIPT,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_CLAIMED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUSES,
    Base,
    Job,
    MemorySession,
    Observation,
    Transcript,
    TranscriptEntry,
)

__all__ = [
    "Base",
    "Database",
    "JOB_KIND_PROCESS_TRANSCRIPT",
    "JOB_STATUSES",
    "JOB_STATUS_CANCELLED",
    "JOB_STATUS_CLAIMED",
    "JOB_STATUS_COMPLETED",
    "JOB_STATUS_FAILED",
    "JOB_STATUS_QUEUED",
    "JOB_STATUS_RUNNING",
    "Job",
    "MemorySession",
    "Observation",
    "Transcript",
    "TranscriptEntry",
    "database",
]
