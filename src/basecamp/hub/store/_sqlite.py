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


@contextmanager
def reading(db_path: Path) -> Iterator[sqlite3.Connection]:
    """A read connection with the ``sqlite3.Row`` factory, always closed on exit."""
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
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
