"""Concurrency pragmas for the hub SQLite store.

The daemon serves many concurrent readers/writers (agent telemetry, result
reports, waits). Without WAL and a busy_timeout, a read overlapping a writer's
commit raised ``database is locked`` into the wait path, which ``handle_wait``
swallowed as "not awaitable". These tests pin the fix: connections run in WAL
mode with a retry window, and a contended write waits instead of failing.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from basecamp.hub.store import Store


def test_store_connections_enable_wal_and_busy_timeout(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    for acquire in (store._reading, lambda: store._writing(immediate=True)):
        with acquire() as conn:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] > 0


def test_store_write_retries_under_concurrent_write_lock(tmp_path: Path) -> None:
    # A second writer that arrives while the write lock is held must wait for it
    # (busy_timeout) rather than raising "database is locked" immediately — the
    # failure mode that surfaced in the wait path under telemetry/report load.
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    held = threading.Event()
    release = threading.Event()

    def hold_write_lock() -> None:
        # Each thread opens its own connection, so the default check_same_thread
        # guard is respected.
        with store._writing(immediate=True):
            held.set()
            release.wait(timeout=5)

    holder = threading.Thread(target=hold_write_lock)
    holder.start()
    assert held.wait(timeout=5), "holder did not acquire the write lock"

    outcome: dict[str, object] = {}

    def contend() -> None:
        try:
            with store._writing(immediate=True) as conn:
                conn.execute("SELECT 1").fetchone()
            outcome["ok"] = True
        except BaseException as exc:  # noqa: BLE001 — record any failure verbatim
            outcome["error"] = repr(exc)

    contender = threading.Thread(target=contend)
    contender.start()
    time.sleep(0.3)
    # The contender is genuinely blocked on the held lock, not failed fast.
    assert contender.is_alive(), "contender was not blocked on the write lock"

    release.set()
    contender.join(timeout=6)
    holder.join(timeout=6)

    assert outcome.get("ok"), f"store write failed under contention: {outcome.get('error')}"


def test_store_read_succeeds_during_concurrent_writer(tmp_path: Path) -> None:
    # The reported bug: a wait's projection read racing a writer's commit. Under
    # WAL a reader proceeds against a consistent snapshot and does not block on,
    # or raise against, an open writer.
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    held = threading.Event()
    release = threading.Event()

    def hold_open_writer() -> None:
        with store._writing(immediate=True) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS marker (x INTEGER)")
            held.set()
            release.wait(timeout=5)

    writer = threading.Thread(target=hold_open_writer)
    writer.start()
    assert held.wait(timeout=5)

    try:
        with store._reading() as conn:
            rows = conn.execute("SELECT 1 AS v").fetchall()
        assert [row["v"] for row in rows] == [1]
    finally:
        release.set()
        writer.join(timeout=6)
