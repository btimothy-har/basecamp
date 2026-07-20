"""SQLite-backed persistence for the hub daemon, composed from per-object stores.

The consumed surface is deliberately small: ``Store``, the four error classes,
and the two helpers service code shares. Each table-owning data object is a
package under ``store/`` owning its own ``schema``/``writer``/``reader``;
``directory``, ``policy``, and ``summary`` are cross-table read-models with no
schema of their own.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from basecamp.core.paths import DAEMON_DB, TASKS_DIR

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
from .summary import SummaryMixin
from .text import (
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
    """Hub daemon persistence layer backed by SQLite."""

    def __init__(self, db_path: str | Path | None = None, task_dir: str | Path | None = None) -> None:
        self.db_path = Path(db_path).expanduser() if db_path is not None else DAEMON_DB
        self.task_dir = Path(task_dir).expanduser() if task_dir is not None else TASKS_DIR
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _init_db(self) -> None:
        """Create each object's tables and run its column migrations on one connection.

        Order-independent: every table uses ``IF NOT EXISTS`` and holds no declared FK
        constraint, so each object initializes its own schema in isolation.
        """
        with self._connect() as connection:
            self._init_agents_schema(connection)
            self._init_runs_schema(connection)
            self._init_messages_schema(connection)
            self._init_workstreams_schema(connection)
            self._init_raw_pi_thread_schema(connection)
            self._init_analysis_schema(connection)
