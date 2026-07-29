"""Shared SQLite plumbing for the hub store.

The connection managers, the idempotent column-migration helper, and the
JSON-column codec that every per-object mixin builds on — the DB-side analogue
of ``text.py``.

``reading``/``writing`` own connection lifecycle: the row factory, the
transaction, and — unlike a bare ``with sqlite3.connect(...) as conn`` (which
commits but never closes) — the ``close()``. ``ensure_column`` collapses the
PRAGMA-guarded idempotent ALTER. ``load_json_column`` decodes a JSON text column
defensively — malformed or non-string values yield the default, never a raise
(the store previously did this in some readers and not others).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _configure(connection: sqlite3.Connection) -> None:
    """Switch the connection to WAL mode.

    WAL lets readers run against a snapshot alongside a writer, so the
    read-during-write contention that surfaced as ``database is locked`` in the
    wait path cannot occur. WAL is a file-level property: the first connection to
    a rollback-mode DB flips it, and every later call is a no-op read. (sqlite3
    already defaults ``busy_timeout`` to 5000ms, so no retry pragma is needed.)
    """
    connection.execute("PRAGMA journal_mode=WAL")


@contextmanager
def reading(db_path: Path) -> Iterator[sqlite3.Connection]:
    """A read connection with the ``sqlite3.Row`` factory, always closed on exit."""
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    _configure(connection)
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def writing(db_path: Path, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    """A write connection: commit on success, rollback on error, always closed.

    ``immediate=True`` takes the write lock up front (``BEGIN IMMEDIATE``) for the
    read-modify-write guards that must not race a concurrent writer.
    """
    connection = sqlite3.connect(db_path)
    _configure(connection)
    try:
        if immediate:
            connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    finally:
        connection.close()


def ensure_column(connection: sqlite3.Connection, table: str, name: str, decl: str) -> None:
    """Add ``name`` to ``table`` if absent — the idempotent PRAGMA-guarded ALTER."""
    names = {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if name not in names:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def load_json_column(value: Any, default: Any = None) -> Any:
    """Decode a JSON text column; a non-string or malformed value yields ``default``."""
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def dump_json_column(value: Any) -> str:
    """Encode a value for storage in a JSON text column."""
    return json.dumps(value)
