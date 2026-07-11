"""SQLite-backed persistence for daemon agents and runs.

The package's consumed surface is deliberately small: ``Store``, the four
error classes, and the two helpers service code shares. Submodule constants
(message statuses, summary limits, ...) are imported directly from their
defining module by in-package code.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .agents import AgentsMixin
from .analysis import AnalysisMixin
from .directory import DirectoryMixin
from .errors import (
    ActiveRunExistsError,
    DuplicateAgentHandleError,
    DuplicateWorkstreamSlugError,
    WorkstreamNotFoundError,
)
from .messages import MessagesMixin
from .policy import PolicyMixin
from .raw_pi_thread import RawPiThreadMixin
from .runs import RunsMixin
from .schema import SchemaMixin
from .summary import SummaryMixin
from .text import (
    default_db_path,
    default_tasks_dir,
    is_message_delivery_terminal,
    safe_product_role,
)
from .workstreams import WorkstreamsMixin

__all__ = [
    "ActiveRunExistsError",
    "DuplicateAgentHandleError",
    "DuplicateWorkstreamSlugError",
    "Store",
    "WorkstreamNotFoundError",
    "is_message_delivery_terminal",
    "safe_product_role",
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
    RawPiThreadMixin,
    AnalysisMixin,
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
