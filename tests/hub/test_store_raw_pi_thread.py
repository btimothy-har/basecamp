"""Tests for daemon store raw-pi-thread persistence (node by node)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from basecamp.hub.store import Store
from basecamp.hub.store.raw_pi_thread import RawPiThreadNode


def _node(entry_id: str, parent_id: str | None, text: str) -> RawPiThreadNode:
    return RawPiThreadNode(entry_id=entry_id, parent_id=parent_id, entry_json=text)


def test_record_then_get_head_and_live_branch(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    seq = store.record_raw_pi_thread(
        owner_id="session-1",
        session_id="pi-sess-1",
        session_file="/home/u/.pi/sessions/pi-sess-1.jsonl",
        leaf_id="e2",
        nodes=[_node("e1", None, "root"), _node("e2", "e1", "leaf")],
    )
    assert seq == 1

    head = store.get_raw_pi_thread("session-1")
    assert head is not None
    assert head.owner_id == "session-1"
    assert head.session_id == "pi-sess-1"
    assert head.session_file == "/home/u/.pi/sessions/pi-sess-1.jsonl"
    assert head.leaf_id == "e2"
    assert head.latest_seq == 1

    thread = store.get_raw_pi_thread_nodes("session-1")
    assert thread.live == ["root", "leaf"]
    assert thread.abandoned == []


def test_record_inserts_only_new_nodes_and_bumps_seq(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.record_raw_pi_thread(
        owner_id="s", session_id="pi", session_file=None, leaf_id="e1", nodes=[_node("e1", None, "root")]
    )
    # second turn re-sends e1 (immutable) plus a new e2
    seq2 = store.record_raw_pi_thread(
        owner_id="s",
        session_id="pi",
        session_file=None,
        leaf_id="e2",
        nodes=[_node("e1", None, "REWRITTEN"), _node("e2", "e1", "leaf")],
    )

    assert seq2 == 2
    # e1 kept its original content (insert-only; DO NOTHING on conflict)
    assert store.get_raw_pi_thread_nodes("s").live == ["root", "leaf"]

    with sqlite3.connect(db_path) as connection:
        seqs = dict(
            connection.execute(
                "SELECT entry_id, first_seen_seq FROM raw_pi_thread_node WHERE owner_id = ?", ("s",)
            ).fetchall()
        )
        total = connection.execute("SELECT COUNT(*) FROM raw_pi_thread_node WHERE owner_id = ?", ("s",)).fetchone()[0]

    assert seqs == {"e1": 1, "e2": 2}
    assert total == 2


def test_resend_without_new_nodes_does_not_bump_seq(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    seq1 = store.record_raw_pi_thread(
        owner_id="s", session_id="pi", session_file=None, leaf_id="e1", nodes=[_node("e1", None, "root")]
    )
    # replay the identical report (same leaf, no new nodes) — e.g. a reconnect resend
    seq2 = store.record_raw_pi_thread(
        owner_id="s", session_id="pi", session_file=None, leaf_id="e1", nodes=[_node("e1", None, "root")]
    )

    assert seq1 == 1
    assert seq2 == 1  # unchanged: no redundant analysis is triggered
    assert store.get_raw_pi_thread("s").latest_seq == 1


def test_rewind_to_an_existing_leaf_bumps_seq(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    store.record_raw_pi_thread(
        owner_id="s",
        session_id="pi",
        session_file=None,
        leaf_id="e2",
        nodes=[_node("e1", None, "root"), _node("e2", "e1", "leaf")],
    )
    # rewind to e1: no new nodes, but the leaf moved, so the branch changed
    seq = store.record_raw_pi_thread(
        owner_id="s", session_id="pi", session_file=None, leaf_id="e1", nodes=[_node("e1", None, "root")]
    )

    assert seq == 2  # leaf moved e2 -> e1 counts as a change even with no new nodes
    head = store.get_raw_pi_thread("s")
    assert head is not None
    assert head.leaf_id == "e1"
    assert store.get_raw_pi_thread_nodes("s").live == ["root"]


def test_live_branch_follows_the_current_leaf_after_a_fork(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    store.record_raw_pi_thread(
        owner_id="s",
        session_id="pi",
        session_file=None,
        leaf_id="e2",
        nodes=[_node("e1", None, "root"), _node("e2", "e1", "old-leaf")],
    )
    # fork off e1: e3 becomes the new leaf, e2 is now an abandoned branch
    store.record_raw_pi_thread(
        owner_id="s", session_id="pi", session_file=None, leaf_id="e3", nodes=[_node("e3", "e1", "new-leaf")]
    )

    assert store.get_raw_pi_thread_nodes("s").live == ["root", "new-leaf"]


def test_include_abandoned_separates_roads_not_taken_from_the_main_thread(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    store.record_raw_pi_thread(
        owner_id="s",
        session_id="pi",
        session_file=None,
        leaf_id="e2",
        nodes=[_node("e1", None, "root"), _node("e2", "e1", "abandoned")],
    )
    # rewind off e1: e3 becomes the live leaf, e2's branch is abandoned
    store.record_raw_pi_thread(
        owner_id="s", session_id="pi", session_file=None, leaf_id="e3", nodes=[_node("e3", "e1", "live")]
    )

    # default: main thread only; the abandoned branch is retained but not returned
    default = store.get_raw_pi_thread_nodes("s")
    assert default.live == ["root", "live"]
    assert default.abandoned == []

    # opt in: the abandoned branch is reconstructed separately from the main thread
    full = store.get_raw_pi_thread_nodes("s", include_abandoned=True)
    assert full.live == ["root", "live"]
    assert full.abandoned == [["root", "abandoned"]]


def test_reconstruction_terminates_on_a_cyclic_parent(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    # Parent links are opaque and unvalidated; a malformed self-cycle must not loop.
    store.record_raw_pi_thread(
        owner_id="s", session_id="pi", session_file=None, leaf_id="e1", nodes=[_node("e1", "e1", "loop")]
    )
    assert store.get_raw_pi_thread_nodes("s").live == ["loop"]  # visited once, cycle stopped

    # A two-node cycle terminates too (each node visited exactly once).
    store.record_raw_pi_thread(
        owner_id="t",
        session_id="pi",
        session_file=None,
        leaf_id="a",
        nodes=[_node("a", "b", "A"), _node("b", "a", "B")],
    )
    live = store.get_raw_pi_thread_nodes("t").live
    assert sorted(live) == ["A", "B"]
    assert len(live) == 2


def test_missing_session_returns_empty(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    assert store.get_raw_pi_thread("missing") is None

    thread = store.get_raw_pi_thread_nodes("missing", include_abandoned=True)
    assert thread.live == []
    assert thread.abandoned == []
