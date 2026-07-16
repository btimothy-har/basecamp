"""Tests for the ``transcript_nodes`` store (uuid-keyed, insert-only)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from basecamp.hub.claude.store import SessionStore


def _node(uuid: str, **overrides: Any) -> dict[str, Any]:
    node: dict[str, Any] = {
        "uuid": uuid,
        "parent_uuid": None,
        "logical_parent_uuid": None,
        "type": "assistant",
        "is_sidechain": 0,
        "timestamp": f"2026-01-01T00:00:0{uuid[-1]}+00:00",
        "seq": 0,
        "line_json": f'{{"uuid":"{uuid}"}}',
    }
    node.update(overrides)
    return node


def test_record_nodes_inserts_and_counts(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")

    inserted = store.record_nodes(
        session_id="s1",
        episode_id="e1",
        nodes=[_node("a", seq=0), _node("b", parent_uuid="a", seq=1)],
    )

    assert inserted == 2
    assert store.count_transcript_nodes("s1") == 2
    assert store.count_transcript_nodes() == 2


def test_record_nodes_is_idempotent_on_uuid(tmp_path: Path) -> None:
    # PreCompact + SessionEnd both read the full file; the second pass inserts nothing.
    store = SessionStore(db_path=tmp_path / "daemon.db")
    nodes = [_node("a", seq=0), _node("b", seq=1)]

    assert store.record_nodes(session_id="s1", episode_id="e1", nodes=nodes) == 2
    assert store.record_nodes(session_id="s1", episode_id="e1", nodes=nodes) == 0
    assert store.count_transcript_nodes("s1") == 2


def test_empty_nodes_is_a_noop(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")

    assert store.record_nodes(session_id="s1", episode_id="e1", nodes=[]) == 0
    assert store.count_transcript_nodes() == 0


def test_first_writer_wins_dedups_fork_copies(tmp_path: Path) -> None:
    # A fork's transcript re-copies the parent's nodes verbatim (same uuids, its own
    # sessionId). Ingesting it inserts only the fork's genuinely new nodes, and the
    # shared node keeps the parent's session label — lineage is uuid overlap, not the
    # session_id column.
    store = SessionStore(db_path=tmp_path / "daemon.db")
    store.record_nodes(session_id="parent", episode_id="ep", nodes=[_node("shared", seq=0)])

    inserted = store.record_nodes(
        session_id="fork",
        episode_id="ef",
        nodes=[_node("shared", seq=0), _node("fork-only", parent_uuid="shared", seq=1)],
    )

    assert inserted == 1
    assert store.count_transcript_nodes() == 2
    with sqlite3.connect(tmp_path / "daemon.db") as connection:
        connection.row_factory = sqlite3.Row
        shared = connection.execute("SELECT session_id FROM transcript_nodes WHERE uuid = 'shared'").fetchone()
        fork_only = connection.execute("SELECT session_id FROM transcript_nodes WHERE uuid = 'fork-only'").fetchone()
    assert shared["session_id"] == "parent"
    assert fork_only["session_id"] == "fork"


def test_record_nodes_persists_all_lifted_columns(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")

    store.record_nodes(
        session_id="s1",
        episode_id="e1",
        nodes=[
            _node(
                "boundary",
                parent_uuid=None,
                logical_parent_uuid="pre-leaf",
                type="system",
                is_sidechain=1,
                timestamp="2026-01-01T00:00:09+00:00",
                seq=42,
                line_json='{"uuid":"boundary","subtype":"compact_boundary"}',
            )
        ],
    )

    with sqlite3.connect(tmp_path / "daemon.db") as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM transcript_nodes WHERE uuid = 'boundary'").fetchone()
    assert row["session_id"] == "s1"
    assert row["episode_id"] == "e1"
    assert row["logical_parent_uuid"] == "pre-leaf"
    assert row["type"] == "system"
    assert row["is_sidechain"] == 1
    assert row["seq"] == 42
    assert row["line_json"] == '{"uuid":"boundary","subtype":"compact_boundary"}'
    assert row["first_seen_at"]


def test_record_nodes_stamps_subagent_linkage_and_has_agent_nodes(tmp_path: Path) -> None:
    # A sidecar's nodes carry the batch-level parent-linkage keys; the main thread's do not.
    store = SessionStore(db_path=tmp_path / "daemon.db")

    store.record_nodes(session_id="s1", episode_id="e1", nodes=[_node("m1", is_sidechain=0)])
    store.record_nodes(
        session_id="s1",
        episode_id="e1",
        nodes=[_node("x1", is_sidechain=1), _node("x2", is_sidechain=1)],
        source_agent_id="alpha",
        source_tool_use_id="toolu_alpha",
    )

    with sqlite3.connect(tmp_path / "daemon.db") as connection:
        connection.row_factory = sqlite3.Row
        main = connection.execute("SELECT * FROM transcript_nodes WHERE uuid = 'm1'").fetchone()
        sub = connection.execute("SELECT * FROM transcript_nodes WHERE uuid = 'x1'").fetchone()
    assert (main["source_agent_id"], main["source_tool_use_id"]) == (None, None)
    assert (sub["source_agent_id"], sub["source_tool_use_id"]) == ("alpha", "toolu_alpha")

    assert store.has_agent_nodes("s1", "alpha") is True
    assert store.has_agent_nodes("s1", "beta") is False
    assert store.has_agent_nodes("other", "alpha") is False


def test_null_episode_id_is_allowed(tmp_path: Path) -> None:
    # A node first seen after its episode closed (SessionEnd tail) may carry no episode.
    store = SessionStore(db_path=tmp_path / "daemon.db")

    assert store.record_nodes(session_id="s1", episode_id=None, nodes=[_node("a")]) == 1
    with sqlite3.connect(tmp_path / "daemon.db") as connection:
        episode = connection.execute("SELECT episode_id FROM transcript_nodes WHERE uuid = 'a'").fetchone()[0]
    assert episode is None
