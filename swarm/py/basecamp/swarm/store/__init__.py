"""SQLite-backed persistence for daemon agents and runs."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .agents import AgentsMixin
from .directory import DirectoryMixin
from .errors import (
    ActiveRunExistsError,
    DuplicateAgentHandleError,
    DuplicateWorkstreamSlugError,
    WorkstreamNotFoundError,
)
from .messages import (
    MESSAGE_STATUS_ACCEPTED,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_QUEUED,
    MESSAGE_STATUS_SENT,
    MESSAGE_STATUS_UNAVAILABLE,
    MESSAGE_STATUS_UNKNOWN,
    MESSAGE_STATUSES,
    MESSAGE_TERMINAL_DELIVERY_STATUSES,
    MessagesMixin,
)
from .policy import AgentRelation, PolicyMixin
from .runs import TERMINAL_STATUSES, RunsMixin
from .schema import SchemaMixin
from .summary import (
    RUN_MESSAGES_DEFAULT_LIMIT,
    RUN_MESSAGES_MAX_LIMIT,
    RUN_SUMMARY_ACTIVITY_LIMIT,
    RUN_SUMMARY_DEFAULT_LIMIT,
    RUN_SUMMARY_MAX_LIMIT,
    RUN_SUMMARY_SKILLS_LIMIT,
    RUN_SUMMARY_TASK_LOG_MAX_BYTES,
    RUN_SUMMARY_TASK_PLAN_LIMIT,
    SummaryMixin,
)
from .text import (
    RUN_SUMMARY_DISPLAY_CHARS,
    RUN_SUMMARY_PREVIEW_CHARS,
    _safe_product_role,
    default_db_path,
    default_tasks_dir,
    is_message_delivery_terminal,
)
from .workstreams import WORKSTREAM_STATUSES, WorkstreamsMixin

__all__ = [
    "MESSAGE_STATUS_ACCEPTED",
    "MESSAGE_STATUS_FAILED",
    "MESSAGE_STATUS_QUEUED",
    "MESSAGE_STATUS_SENT",
    "MESSAGE_STATUS_UNAVAILABLE",
    "MESSAGE_STATUS_UNKNOWN",
    "MESSAGE_STATUSES",
    "MESSAGE_TERMINAL_DELIVERY_STATUSES",
    "RUN_MESSAGES_DEFAULT_LIMIT",
    "RUN_MESSAGES_MAX_LIMIT",
    "RUN_SUMMARY_ACTIVITY_LIMIT",
    "RUN_SUMMARY_DEFAULT_LIMIT",
    "RUN_SUMMARY_DISPLAY_CHARS",
    "RUN_SUMMARY_MAX_LIMIT",
    "RUN_SUMMARY_PREVIEW_CHARS",
    "RUN_SUMMARY_SKILLS_LIMIT",
    "RUN_SUMMARY_TASK_LOG_MAX_BYTES",
    "RUN_SUMMARY_TASK_PLAN_LIMIT",
    "TERMINAL_STATUSES",
    "WORKSTREAM_STATUSES",
    "ActiveRunExistsError",
    "AgentRelation",
    "DuplicateAgentHandleError",
    "DuplicateWorkstreamSlugError",
    "Store",
    "WorkstreamNotFoundError",
    "_safe_product_role",
    "default_db_path",
    "default_tasks_dir",
    "is_message_delivery_terminal",
]


class Store(
    SchemaMixin,
    AgentsMixin,
    MessagesMixin,
    RunsMixin,
    PolicyMixin,
    DirectoryMixin,
    SummaryMixin,
    WorkstreamsMixin,
):
    """Daemon persistence layer backed by SQLite."""

    def __init__(self, db_path: str | Path | None = None, task_dir: str | Path | None = None) -> None:
        self.db_path = Path(db_path).expanduser() if db_path is not None else default_db_path()
        self.task_dir = Path(task_dir).expanduser() if task_dir is not None else default_tasks_dir()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()
