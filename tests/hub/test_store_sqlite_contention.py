"""WAL mode for the hub SQLite store.

The daemon serves many concurrent readers/writers (agent telemetry, result
reports, waits). Without WAL, a reader whose read transaction overlapped a
writer's commit contended for the lock and raised ``database is locked`` into
the wait path, which ``handle_wait`` swallowed as "not awaitable". WAL lets
readers run against a snapshot alongside a writer; these tests pin that the
store runs in WAL and that a writer commits while a reader holds an open read.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from basecamp.hub.store import Store


def test_store_connections_run_in_wal_mode(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    for acquire in (store._reading, lambda: store._writing(immediate=True)):
        with acquire() as conn:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_store_writer_commits_while_a_read_transaction_is_open(tmp_path: Path) -> None:
    # WAL's defining benefit: a writer commits while a reader holds an open read
    # transaction. In rollback-journal mode the reader's SHARED lock blocks the
    # writer's EXCLUSIVE commit, so this raises "database is locked" once the
    # default busy_timeout elapses — the failure mode that surfaced in the wait
    # path. Each thread opens its own connection, so check_same_thread is respected.
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    read_held = threading.Event()
    release_reader = threading.Event()

    def hold_read_transaction() -> None:
        conn = sqlite3.connect(db_path)
        conn.execute("BEGIN")
        # Read real table content so the open transaction holds a SHARED lock
        # (a constant `SELECT 1` touches no table and acquires no lock).
        conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        read_held.set()
        release_reader.wait(timeout=5)
        conn.rollback()
        conn.close()

    reader = threading.Thread(target=hold_read_transaction)
    reader.start()
    assert read_held.wait(timeout=5), "reader did not acquire a read transaction"

    writer_error: dict[str, object] = {}
    still_held = False
    try:
        with store._writing() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS marker (x INTEGER)")
            conn.execute("INSERT INTO marker (x) VALUES (1)")
        # Captured before releasing the reader: under WAL the write committed
        # while the read transaction was still open.
        still_held = reader.is_alive()
    except BaseException as exc:  # noqa: BLE001 — record any failure verbatim
        writer_error["error"] = repr(exc)
    finally:
        release_reader.set()
        reader.join(timeout=6)

    assert not writer_error, f"store write failed while a read transaction was open: {writer_error.get('error')}"
    assert still_held, "writer blocked on the open read transaction (expected to commit under WAL)"
