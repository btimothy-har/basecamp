"""SQLite-backed persistence for the Claude hub daemon, composed from per-object mixins.

Two entities, mirroring Claude Code's own model rather than the Pi ``agents`` row:

- ``sessions`` — the durable actor, keyed by the native ``CLAUDE_CODE_SESSION_ID``
  (stable across resume and ``/clear``). Never "ended".
- ``episodes`` — one row per SessionStart→SessionEnd engagement. Liveness is an
  episode with ``ended_at IS NULL``; the durable session row is never touched by a
  SessionEnd. This is what lets the hook stop special-casing ``clear``/``resume``.

This package is deliberately independent of the legacy Pi ``hub/store/`` package:
the Claude section owns its own database so it can be promoted (and the Pi side
deleted outright) without a shared-schema migration. It never imports from
``hub/store/``. The composition idiom — a ``SessionStore`` multiple-inheriting
per-object ``*Mixin`` classes whose ``_init_<object>_schema`` run on one
connection — matches ``hub/store/__init__.py`` so the two read alike.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ..paths import claude_daemon_db_path
from .episodes import EpisodesMixin
from .sessions import SessionsMixin

__all__ = ["SessionStore"]


class SessionStore(SessionsMixin, EpisodesMixin):
    """Durable identity (``sessions``) + engagement liveness (``episodes``)."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path).expanduser() if db_path is not None else claude_daemon_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _init_db(self) -> None:
        """Create both objects' tables on one connection.

        Order-independent: every table uses ``IF NOT EXISTS`` and holds no declared
        FK constraint (``episodes.session_id`` is a logical ref), so each object
        initializes its own schema in isolation — same convention as the Pi store.
        """

        with self._connect() as connection:
            self._init_sessions_schema(connection)
            self._init_episodes_schema(connection)
