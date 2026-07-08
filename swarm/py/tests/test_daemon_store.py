"""Tests for daemon SQLite store initialization and agent upsert."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from basecamp.swarm.store import (
    ActiveRunExistsError,
    DuplicateAgentHandleError,
    DuplicateWorkstreamSlugError,
    Store,
    WorkstreamNotFoundError,
    is_message_delivery_terminal,
)


def test_store_initializes_required_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    Store(db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()

    table_names = {row[0] for row in rows}
    assert "agents" in table_names
    assert "runs" in table_names
    assert "run_events" in table_names
    assert "messages" in table_names
    assert "workstreams" in table_names
    assert "workstream_agents" in table_names


def test_store_adds_messages_table_to_existing_database(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE agents (
                id TEXT PRIMARY KEY,
                parent_id TEXT,
                sibling_group TEXT,
                depth INTEGER,
                role TEXT,
                session_name TEXT,
                cwd TEXT,
                created_at TEXT,
                last_seen_at TEXT,
                current_run_id TEXT,
                agent_handle TEXT,
                agent_type TEXT,
                run_kind TEXT,
                model TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE runs (
                id TEXT PRIMARY KEY,
                agent_id TEXT,
                status TEXT CHECK(status IN ('pending','running','completed','failed')),
                dispatcher_id TEXT,
                spec_json TEXT,
                report_token_hash TEXT,
                result TEXT,
                error TEXT,
                exit_code INTEGER,
                created_at TEXT,
                started_at TEXT,
                ended_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE run_events (
                run_id TEXT,
                seq INTEGER,
                kind TEXT,
                payload_json TEXT,
                ts TEXT,
                PRIMARY KEY (run_id, seq)
            )
            """
        )

    Store(db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(messages)").fetchall()}

    assert columns == {
        "id",
        "root_id",
        "sender_node_id",
        "sender_handle",
        "target_agent_id",
        "target_handle",
        "content",
        "interrupt",
        "status",
        "error",
        "created_at",
        "sent_at",
        "queued_at",
        "failed_at",
    }


def test_store_migrates_agent_handle_column_and_backfills_existing_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE agents (
                id TEXT PRIMARY KEY,
                parent_id TEXT,
                sibling_group TEXT,
                depth INTEGER,
                role TEXT,
                session_name TEXT,
                cwd TEXT,
                created_at TEXT,
                last_seen_at TEXT,
                current_run_id TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO agents (id, parent_id, sibling_group, depth, role, session_name, cwd, created_at, last_seen_at)
            VALUES ('legacy-id', NULL, NULL, 0, 'session', 'legacy', '/tmp', 'created', 'seen')
            """
        )

    Store(db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agents)").fetchall()}
        row = connection.execute("SELECT agent_handle FROM agents WHERE id = 'legacy-id'").fetchone()
        indexes = connection.execute("PRAGMA index_list(agents)").fetchall()

    assert "agent_handle" in columns
    assert row == ("legacy-id",)
    assert any(index[1] == "idx_agents_agent_handle_unique" and index[2] for index in indexes)


def test_store_migrates_agent_model_column(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE agents (
                id TEXT PRIMARY KEY,
                parent_id TEXT,
                sibling_group TEXT,
                depth INTEGER,
                role TEXT,
                session_name TEXT,
                cwd TEXT,
                created_at TEXT,
                last_seen_at TEXT,
                current_run_id TEXT,
                agent_handle TEXT,
                agent_type TEXT,
                run_kind TEXT
            )
            """
        )

    Store(db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agents)").fetchall()}

    assert "model" in columns


def test_upsert_agent_persists_and_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="parent-1",
        sibling_group="sg",
        depth=2,
        role="agent",
        session_name="session-b",
        cwd="/tmp/b",
    )

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, parent_id, depth, session_name, cwd
            FROM agents
            WHERE id = 'agent-1'
            """
        ).fetchall()

    assert len(rows) == 1
    assert rows[0] == ("agent-1", "parent-1", 2, "session-b", "/tmp/b")


def test_upsert_agent_persists_gets_and_preserves_handle(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        agent_handle="readable",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
        model="claude-sonnet-4-5",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-b",
        cwd="/tmp/b",
    )

    agent = store.get_agent("agent-1")
    by_handle = store.get_agent_by_handle("readable")
    assert agent is not None
    assert agent["agent_handle"] == "readable"
    assert agent["model"] == "claude-sonnet-4-5"
    assert by_handle is not None
    assert by_handle["id"] == "agent-1"


def test_get_subtree_agent_ids_returns_root_and_descendants_only(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="child",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="child",
        cwd="/tmp/child",
    )
    store.upsert_agent(
        agent_id="grandchild",
        parent_id="child",
        sibling_group="child",
        depth=2,
        role="agent",
        session_name="grandchild",
        cwd="/tmp/grandchild",
    )
    store.upsert_agent(
        agent_id="sibling-root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="sibling-root",
        cwd="/tmp/sibling-root",
    )

    assert set(store.get_subtree_agent_ids("root")) == {"root", "child", "grandchild"}


def test_upsert_agent_preserves_sibling_group_when_unset(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        parent_id="parent-1",
        sibling_group="parent-1",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="parent-1",
        sibling_group=None,
        depth=1,
        role="agent",
        session_name="session-b",
        cwd="/tmp/b",
    )

    agent = store.get_agent("agent-1")
    assert agent is not None
    assert agent["sibling_group"] == "parent-1"


def test_upsert_agent_rejects_duplicate_handle(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        agent_handle="shared",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )

    with pytest.raises(DuplicateAgentHandleError):
        store.upsert_agent(
            agent_id="agent-2",
            agent_handle="shared",
            parent_id=None,
            sibling_group="sg",
            depth=1,
            role="agent",
            session_name="session-b",
            cwd="/tmp/b",
        )


def test_upsert_agent_rejects_fallback_handle_collision(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        agent_handle="agent-2",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )

    with pytest.raises(DuplicateAgentHandleError):
        store.upsert_agent(
            agent_id="agent-2",
            parent_id=None,
            sibling_group="sg",
            depth=1,
            role="agent",
            session_name="session-b",
            cwd="/tmp/b",
        )


def test_create_message_persists_accepted_message(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.create_message(
        message_id="message-1",
        root_id="root-1",
        sender_node_id="sender-1",
        sender_handle=None,
        target_agent_id="target-1",
        target_handle="target-handle",
        content="hello peer",
        interrupt=True,
    )

    message = store.get_message("message-1")

    assert message is not None
    assert message["id"] == "message-1"
    assert message["root_id"] == "root-1"
    assert message["sender_node_id"] == "sender-1"
    assert message["sender_handle"] is None
    assert message["target_agent_id"] == "target-1"
    assert message["target_handle"] == "target-handle"
    assert message["content"] == "hello peer"
    assert message["interrupt"] == 1
    assert message["status"] == "accepted"
    assert message["error"] is None
    assert message["created_at"] is not None
    assert message["sent_at"] is None
    assert message["queued_at"] is None
    assert message["failed_at"] is None


def test_message_lifecycle_transitions_and_missing_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    _create_message(store, "sent-message")
    _create_message(store, "queued-message")
    _create_message(store, "failed-message")
    _create_message(store, "unavailable-message")

    assert store.mark_message_sent("sent-message") is True
    assert store.mark_message_queued("queued-message") is True
    assert store.mark_message_failed("failed-message", "delivery failed") is True
    assert store.mark_message_unavailable("unavailable-message", "target missing") is True
    assert store.mark_message_sent("missing-message") is False
    assert store.mark_message_queued("missing-message") is False
    assert store.mark_message_failed("missing-message", "missing") is False
    assert store.mark_message_unavailable("missing-message", "missing") is False

    sent = store.get_message("sent-message")
    queued = store.get_message("queued-message")
    failed = store.get_message("failed-message")
    unavailable = store.get_message("unavailable-message")

    assert sent is not None
    assert sent["status"] == "sent"
    assert sent["sent_at"] is not None
    assert queued is not None
    assert queued["status"] == "queued"
    assert queued["queued_at"] is not None
    assert queued["error"] is None
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["failed_at"] is not None
    assert failed["error"] == "delivery failed"
    assert unavailable is not None
    assert unavailable["status"] == "unavailable"
    assert unavailable["failed_at"] is not None
    assert unavailable["error"] == "target missing"


def test_message_terminal_states_do_not_get_overwritten(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    for message_id in ["queued-message", "failed-message", "unavailable-message"]:
        _create_message(store, message_id)

    assert store.mark_message_queued("queued-message") is True
    assert store.mark_message_failed("failed-message", "failed") is True
    assert store.mark_message_unavailable("unavailable-message", "unavailable") is True

    assert store.mark_message_sent("queued-message") is False
    assert store.mark_message_failed("queued-message", "late failure") is False
    assert store.mark_message_unavailable("queued-message", "late unavailable") is False
    assert store.mark_message_sent("failed-message") is False
    assert store.mark_message_queued("failed-message") is False
    assert store.mark_message_unavailable("failed-message", "late unavailable") is False
    assert store.mark_message_sent("unavailable-message") is False
    assert store.mark_message_queued("unavailable-message") is False
    assert store.mark_message_failed("unavailable-message", "late failure") is False

    queued = store.get_message("queued-message")
    failed = store.get_message("failed-message")
    unavailable = store.get_message("unavailable-message")

    assert queued is not None
    assert queued["status"] == "queued"
    assert queued["sent_at"] is None
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["sent_at"] is None
    assert unavailable is not None
    assert unavailable["status"] == "unavailable"
    assert unavailable["sent_at"] is None


def test_get_message_status_authorizes_participants_only(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)
    _create_message(store, "message-1")
    assert store.mark_message_failed("message-1", "delivery failed") is True

    sender_status = store.get_message_status("sender-1", "message-1")
    recipient_status = store.get_message_status("target-1", "message-1")
    missing_status = store.get_message_status("sender-1", "missing-message")
    unauthorized_status = store.get_message_status("root-1", "message-1")

    assert sender_status == recipient_status
    assert sender_status["message_id"] == "message-1"
    assert sender_status["status"] == "failed"
    assert sender_status["error"] == "delivery failed"
    assert sender_status["created_at"] is not None
    assert sender_status["failed_at"] is not None
    assert sender_status["sent_at"] is None
    assert sender_status["queued_at"] is None
    assert missing_status == _unknown_message_status("missing-message")
    assert unauthorized_status == _unknown_message_status("message-1")


def test_get_message_status_hides_malformed_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    Store(db_path=db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            """
            INSERT INTO messages (
                id,
                root_id,
                sender_node_id,
                sender_handle,
                target_agent_id,
                target_handle,
                content,
                interrupt,
                status,
                error,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "malformed-message",
                "root-1",
                "sender-1",
                "sender",
                "target-1",
                "target",
                "secret",
                0,
                "bogus",
                "secret error",
                "2026-01-01T00:00:00Z",
            ),
        )

    store = Store(db_path=db_path)

    assert store.get_message_status("sender-1", "malformed-message") == _unknown_message_status("malformed-message")


def test_is_message_delivery_terminal() -> None:
    assert is_message_delivery_terminal("queued") is True
    assert is_message_delivery_terminal("failed") is True
    assert is_message_delivery_terminal("unavailable") is True
    assert is_message_delivery_terminal("unknown") is True
    assert is_message_delivery_terminal("accepted") is False
    assert is_message_delivery_terminal("sent") is False


def test_run_event_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.create_run(
        run_id="run-1",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )
    seq = store.append_run_event(run_id="run-1", kind="turn_end", payload={"turnIndex": 1})
    assert seq == 1

    run = store.get_run("run-1")
    assert run is not None
    assert run["report_token_hash"] == "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

    events = store.get_run_events("run-1")
    assert len(events) == 1
    assert events[0]["kind"] == "turn_end"
    assert events[0]["payload_json"] == {"turnIndex": 1}


def test_create_run_stores_dispatcher_and_updates_current_run(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.create_run(
        run_id="run-dispatch",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )

    run = store.get_run("run-dispatch")
    assert run is not None
    assert run["dispatcher_id"] == "dispatcher-1"

    agent = store.get_agent("agent-1")
    assert agent is not None
    assert agent["current_run_id"] == "run-dispatch"


def test_set_run_pgid_persists_and_get_run_returns_value(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.create_run(
        run_id="run-pgid",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )

    run = store.get_run("run-pgid")
    assert run is not None
    assert run["pgid"] is None

    store.set_run_pgid(run_id="run-pgid", pgid=4321)
    run = store.get_run("run-pgid")
    assert run is not None
    assert run["pgid"] == 4321

    store.set_run_pgid(run_id="run-pgid", pgid=None)
    run = store.get_run("run-pgid")
    assert run is not None
    assert run["pgid"] is None


def test_get_nonterminal_runs_returns_pending_and_running_only(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.create_run(run_id="run-completed", agent_id="agent-completed", dispatcher_id="root", spec={})
    store.set_run_result(run_id="run-completed", status="completed", result="done", error=None)
    store.create_run(run_id="run-failed", agent_id="agent-failed", dispatcher_id="root", spec={})
    store.set_run_result(run_id="run-failed", status="failed", result=None, error="failed")
    store.create_run(run_id="run-running", agent_id="agent-running", dispatcher_id="root", spec={})
    store.set_run_pgid(run_id="run-running", pgid=4321)

    rows = store.get_nonterminal_runs()

    assert rows == [{"id": "run-running", "agent_id": "agent-running", "pgid": 4321, "status": "running"}]


def test_get_agents_current_runs_filters_by_dispatcher(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.create_run(
        run_id="run-owned",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )

    owned = store.get_agents_current_runs(["agent-1"], dispatcher_id="dispatcher-1")
    assert owned == [
        {
            "agent_id": "agent-1",
            "agent_handle": "agent-1",
            "run_id": "run-owned",
            "status": "running",
            "result": None,
            "error": None,
        }
    ]

    owned_by_handle = store.get_agents_current_runs_by_handles(["agent-1"], dispatcher_id="dispatcher-1")
    assert owned_by_handle == owned

    unauthorized = store.get_agents_current_runs(["agent-1"], dispatcher_id="dispatcher-2")
    assert unauthorized == [
        {
            "agent_id": "agent-1",
            "agent_handle": "agent-1",
            "run_id": None,
            "status": None,
            "result": None,
            "error": None,
        }
    ]

    missing = store.get_agents_current_runs(["agent-missing"], dispatcher_id="dispatcher-1")
    assert missing == []


def test_get_agents_current_runs_excludes_sessions_from_wait_projection(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        agent_handle="root-handle",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.create_run(
        run_id="run-session",
        agent_id="root",
        dispatcher_id="root",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )

    assert store.get_agents_current_runs(["root"], dispatcher_id="root") == []
    assert store.get_agents_current_runs_by_handles(["root-handle"], dispatcher_id="root") == []


def test_resolve_agent_root_follows_parents_defensively(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-a1",
        depth=1,
        role="agent",
        session_name="agent-a1",
        cwd="/tmp/a1",
    )
    store.upsert_agent(
        agent_id="lost",
        parent_id="missing-parent",
        sibling_group="sg-lost",
        depth=1,
        role="agent",
        session_name="lost",
        cwd="/tmp/lost",
    )

    assert store.resolve_agent_root("agent-1") == "root"
    assert store.resolve_agent_root("root") == "root"
    assert store.resolve_agent_root("lost") == "lost"
    assert store.resolve_agent_root("missing") is None


def test_can_ask_allows_ancestors_descendants_and_siblings_only(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-a",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="agent-a",
        cwd="/tmp/a",
    )
    store.upsert_agent(
        agent_id="agent-b",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="agent-b",
        cwd="/tmp/b",
    )
    store.upsert_agent(
        agent_id="grandchild",
        parent_id="agent-a",
        sibling_group="agent-a",
        depth=2,
        role="agent",
        session_name="grandchild",
        cwd="/tmp/grandchild",
    )
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="outside-root",
        cwd="/tmp/outside-root",
    )
    store.upsert_agent(
        agent_id="outside-agent",
        parent_id="outside-root",
        sibling_group="outside-root",
        depth=1,
        role="agent",
        session_name="outside-agent",
        cwd="/tmp/outside-agent",
    )

    assert store.can_ask("grandchild", "agent-a") is True
    assert store.can_ask("agent-a", "grandchild") is True
    assert store.can_ask("agent-a", "agent-b") is True
    assert store.can_ask("agent-a", "agent-a") is True
    assert store.can_ask("agent-a", "outside-agent") is False
    assert store.can_ask("root", "outside-root") is False
    assert store.can_ask("agent-a", "missing") is False
    assert store.can_ask("missing", "agent-a") is False


def test_can_message_allows_visible_sessions_agents_and_siblings_only(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-a",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="agent-a",
        cwd="/tmp/a",
    )
    store.upsert_agent(
        agent_id="agent-b",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="agent-b",
        cwd="/tmp/b",
    )
    store.upsert_agent(
        agent_id="grandchild",
        parent_id="agent-a",
        sibling_group="agent-a",
        depth=2,
        role="agent",
        session_name="grandchild",
        cwd="/tmp/grandchild",
    )
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="outside-root",
        cwd="/tmp/outside-root",
    )
    store.upsert_agent(
        agent_id="outside-agent",
        parent_id="outside-root",
        sibling_group="outside-root",
        depth=1,
        role="agent",
        session_name="outside-agent",
        cwd="/tmp/outside-agent",
    )

    assert store.can_message("grandchild", "root") is True
    assert store.can_message("root", "grandchild") is True
    assert store.can_message("agent-a", "agent-b") is True
    assert store.can_message("agent-a", "agent-a") is True
    assert store.can_message("agent-a", "outside-agent") is False
    assert store.can_message("root", "outside-root") is False
    assert store.can_message("agent-a", "missing") is False
    assert store.can_message("missing", "agent-a") is False

    assert store.agent_relation("agent-a", "agent-a") == "self"
    assert store.agent_relation("grandchild", "agent-a") == "parent"
    assert store.agent_relation("grandchild", "root") == "ancestor"
    assert store.agent_relation("root", "agent-a") == "child"
    assert store.agent_relation("root", "grandchild") == "descendant"
    assert store.agent_relation("agent-a", "agent-b") == "peer"
    assert store.agent_relation("agent-a", "outside-agent") == "unknown"
    assert store.agent_relation("agent-a", "missing") == "unknown"


def test_can_cancel_allows_dispatcher_ancestors_only_and_rejects_public_handle_authority(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="parent",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="parent",
        cwd="/tmp/parent",
    )
    store.upsert_agent(
        agent_id="grandchild",
        agent_handle="grandchild-public",
        parent_id="parent",
        sibling_group="parent",
        depth=2,
        role="agent",
        session_name="grandchild",
        cwd="/tmp/grandchild",
    )
    store.create_run(
        run_id="run-grandchild",
        agent_id="grandchild",
        dispatcher_id="parent",
        spec={"task": "work"},
        report_token_hash="hash",
    )
    store.upsert_agent(
        agent_id="unrelated",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="unrelated",
        cwd="/tmp/unrelated",
    )
    store.upsert_agent(
        agent_id="retasked",
        agent_handle="retasked-public",
        parent_id="unrelated",
        sibling_group="unrelated",
        depth=1,
        role="agent",
        session_name="retasked",
        cwd="/tmp/retasked",
    )
    store.create_run(
        run_id="run-retasked",
        agent_id="retasked",
        dispatcher_id="root",
        spec={"task": "retasked work"},
        report_token_hash="hash",
    )

    assert store.can_cancel("parent", "grandchild") is True
    assert store.can_cancel("root", "grandchild") is True
    assert store.can_cancel("root", "retasked") is True
    assert store.can_cancel("unrelated", "grandchild") is False
    assert store.can_cancel("grandchild", "grandchild") is False
    assert store.can_cancel("grandchild", "root") is False


def test_known_public_handle_contact_is_allowed_across_unrelated_roots(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group="outside-root",
        depth=0,
        role="session",
        session_name="outside-root",
        cwd="/tmp/outside-root",
    )
    store.upsert_agent(
        agent_id="outside-agent",
        agent_handle="outside-handle",
        parent_id="outside-root",
        sibling_group="outside-root",
        depth=1,
        role="agent",
        session_name="outside-agent",
        cwd="/tmp/outside-agent",
    )
    store.upsert_agent(
        agent_id="private-agent-id",
        parent_id="outside-root",
        sibling_group="outside-root",
        depth=1,
        role="agent",
        session_name="private-agent",
        cwd="/tmp/private-agent",
    )

    # Without known-handle addressing, an unrelated target stays denied.
    assert store.can_message("root", "outside-agent") is False
    assert store.can_ask("root", "outside-agent") is False

    # A known public handle is a routable contact address across unrelated roots.
    assert store.can_message("root", "outside-agent", addressed_by_public_handle=True) is True
    assert store.can_ask("root", "outside-agent", addressed_by_public_handle=True) is True

    # An agent whose handle falls back to its private id exposes no public handle,
    # so known-handle addressing does not relax private-id routing.
    assert store.can_message("root", "private-agent-id", addressed_by_public_handle=True) is False
    assert store.can_ask("root", "private-agent-id", addressed_by_public_handle=True) is False

    # A missing requester or target is never reachable, even by known handle.
    assert store.can_message("missing", "outside-agent", addressed_by_public_handle=True) is False
    assert store.can_message("root", "missing", addressed_by_public_handle=True) is False


def test_get_root_agent_directory_scopes_to_root_and_excludes_sessions(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-a1",
        depth=1,
        role="agent",
        session_name="agent-a1",
        cwd="/tmp/a1",
    )
    store.upsert_agent(
        agent_id="agent-2",
        parent_id="agent-1",
        sibling_group="sg-a2",
        depth=2,
        role="worker",
        session_name="worker-a2",
        cwd="/tmp/a2",
    )
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group="sg-out",
        depth=0,
        role="session",
        session_name="outside-session",
        cwd="/tmp/out",
    )
    store.upsert_agent(
        agent_id="outside-agent",
        parent_id="outside-root",
        sibling_group="sg-oa",
        depth=1,
        role="agent",
        session_name="outside-agent",
        cwd="/tmp/out-agent",
    )

    store.create_run(
        run_id="run-a1",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="hash",
    )
    store.create_run(
        run_id="run-a2",
        agent_id="agent-2",
        dispatcher_id="dispatcher-2",
        spec={"task": "x"},
        report_token_hash="hash",
    )
    store.set_run_result(
        run_id="run-a2",
        status="completed",
        result="done",
        error=None,
    )

    rows = store.get_root_agent_directory(requester_node_id="agent-2", awaitable=False)
    assert [row["agent_id"] for row in rows] == ["agent-1", "agent-2"]
    assert [row["agent_handle"] for row in rows] == ["agent-1", "agent-2"]
    assert rows[0]["parent_id"] == "root"
    assert rows[1]["parent_id"] == "agent-1"
    assert rows[0]["status"] == "running"
    assert rows[1]["status"] == "completed"
    assert rows[0]["role"] == "agent"
    assert rows[1]["role"] == "worker"
    assert rows[0]["awaitable"] is False
    assert rows[1]["awaitable"] is False
    assert all(row["agent_id"] != "outside-agent" for row in rows)


def test_get_root_agent_directory_includes_sanitized_current_task_and_stable_agent_type(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-a1",
        depth=1,
        role="agent",
        session_name="swift-panda-5604f5",
        cwd="/tmp/a1",
        agent_handle="swift-panda-5604f5",
        agent_type="scout",
    )
    store.create_run(
        run_id="run-old",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={"task": "Initial task", "env": {"SECRET": "do-not-leak"}},
        report_token_hash="hash",
    )
    store.set_run_result(
        run_id="run-old",
        status="completed",
        result="done",
        error=None,
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-a1",
        depth=1,
        role="agent",
        session_name="swift-panda-5604f5",
        cwd="/tmp/a1-retask",
    )
    store.create_run(
        run_id="run-current",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={"task": "Retask \x1b[31mfunctional\x1b[0m\ncheck\x00", "env": {"SECRET": "do-not-leak"}},
        report_token_hash="hash",
    )

    rows = store.get_root_agent_directory(requester_node_id="root", awaitable=False)

    assert len(rows) == 1
    assert rows[0]["agent_handle"] == "swift-panda-5604f5"
    assert rows[0]["agent_type"] == "scout"
    assert rows[0]["task"] == "Retask functional check"
    assert "SECRET" not in rows[0]
    assert "spec_json" not in rows[0]


def test_get_root_agent_directory_excludes_ask_agents_but_run_summary_includes_them(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="normal-agent",
        parent_id="root",
        sibling_group="sg-normal",
        depth=1,
        role="agent",
        session_name="normal-agent",
        cwd="/tmp/normal",
    )
    store.upsert_agent(
        agent_id="ask-agent",
        parent_id="root",
        sibling_group="sg-ask",
        depth=1,
        role="agent",
        session_name="ask-agent",
        cwd="/tmp/ask",
        agent_type="ask",
    )
    store.create_run(
        run_id="run-normal",
        agent_id="normal-agent",
        dispatcher_id="root",
        spec={"task": "normal"},
        report_token_hash="hash",
    )
    store.create_run(
        run_id="run-ask",
        agent_id="ask-agent",
        dispatcher_id="root",
        spec={"task": "ask"},
        report_token_hash="hash",
    )

    directory_rows = store.get_root_agent_directory(requester_node_id="root", awaitable=False)
    summary = store.get_run_summary("root")

    assert [row["agent_id"] for row in directory_rows] == ["normal-agent"]
    assert {agent["agent_handle"] for agent in summary["agents"]} == {"normal-agent", "ask-agent"}
    assert summary["counts"]["total"] == 2


def test_get_root_agent_directory_filters_awaitable_agents_only(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-a1",
        depth=1,
        role="agent",
        session_name="agent-a1",
        cwd="/tmp/a1",
    )
    store.upsert_agent(
        agent_id="agent-2",
        parent_id="agent-1",
        sibling_group="sg-a2",
        depth=2,
        role="worker",
        session_name="worker-a2",
        cwd="/tmp/a2",
    )

    store.create_run(
        run_id="run-a1",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={"task": "x"},
        report_token_hash="hash",
    )
    store.create_run(
        run_id="run-a2",
        agent_id="agent-2",
        dispatcher_id="agent-1",
        spec={"task": "x"},
        report_token_hash="hash",
    )
    store.set_run_result(
        run_id="run-a2",
        status="completed",
        result="done",
        error=None,
    )

    rows = store.get_root_agent_directory(requester_node_id="agent-1", awaitable=True)
    assert [row["agent_id"] for row in rows] == ["agent-2"]
    assert rows[0]["status"] == "completed"
    assert rows[0]["awaitable"] is True


def test_get_root_agent_directory_handles_cycle_and_missing_parent_defensively(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="cycle-a",
        parent_id="cycle-b",
        sibling_group="sg-a",
        depth=1,
        role="agent",
        session_name="cycle-a",
        cwd="/tmp/a",
    )
    store.upsert_agent(
        agent_id="cycle-b",
        parent_id="cycle-a",
        sibling_group="sg-b",
        depth=2,
        role="agent",
        session_name="cycle-b",
        cwd="/tmp/b",
    )
    rows = store.get_root_agent_directory(requester_node_id="cycle-a", awaitable=False)
    assert {row["agent_id"] for row in rows} == {"cycle-a", "cycle-b"}
    assert all(row["role"] != "session" for row in rows)

    store.upsert_agent(
        agent_id="lost",
        parent_id="missing-parent",
        sibling_group="sg-lost",
        depth=3,
        role="agent",
        session_name="lost",
        cwd="/tmp/c",
    )

    rows = store.get_root_agent_directory(requester_node_id="lost", awaitable=False)
    assert [row["agent_id"] for row in rows] == ["lost"]


def test_create_run_rejects_non_terminal_duplicate_for_agent(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.create_run(
        run_id="run-first",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )

    with pytest.raises(ActiveRunExistsError):
        store.create_run(
            run_id="run-second",
            agent_id="agent-1",
            dispatcher_id="dispatcher-1",
            spec={"task": "x"},
            report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        )

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT COUNT(*) AS total FROM runs WHERE agent_id = ?",
            ("agent-1",),
        ).fetchone()
    assert rows is not None
    assert rows[0] == 1


def test_set_run_result_preserves_agent_current_run_id(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.create_run(
        run_id="run-complete",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )
    store.set_run_result(
        run_id="run-complete",
        status="completed",
        result="done",
        error=None,
    )

    agent = store.get_agent("agent-1")
    assert agent is not None
    assert agent["current_run_id"] == "run-complete"


def test_set_run_result_if_unset_preserves_agent_current_run_id(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.create_run(
        run_id="run-failed",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )

    assert (
        store.set_run_result_if_unset(
            run_id="run-failed",
            status="failed",
            result="oops",
            error="agent failed",
        )
        is True
    )

    agent = store.get_agent("agent-1")
    assert agent is not None
    assert agent["current_run_id"] == "run-failed"


def test_get_run_wait_results_includes_nonterminal_and_omits_unknown(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.create_run(
        run_id="run-running",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )
    rows = store.get_run_wait_results(["run-running", "run-missing"])
    assert rows == [{"run_id": "run-running", "status": "running", "result": None, "error": None}]

    rows_terminal = store.get_run_wait_results(["run-running", "run-missing"], terminal_only=True)
    assert rows_terminal == []

    store.set_run_result(
        run_id="run-running",
        status="completed",
        result="done",
        error=None,
    )
    rows = store.get_run_wait_results(["run-running", "run-missing"])
    assert rows == [{"run_id": "run-running", "status": "completed", "result": "done", "error": None}]


def test_get_run_summary_unknown_root_returns_empty_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    result = store.get_run_summary("does-not-exist")

    assert result == {
        "root_id": "does-not-exist",
        "counts": {
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "total": 0,
        },
        "agents": [],
    }


def test_get_run_summary_scope_and_counts_include_descendants(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="child",
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="agent",
        session_name="child-agent",
        cwd="/tmp/child",
    )
    store.upsert_agent(
        agent_id="grandchild",
        parent_id="child",
        sibling_group="sg-grandchild",
        depth=2,
        role="worker",
        session_name="grandchild-agent",
        cwd="/tmp/grandchild",
    )
    store.upsert_agent(
        agent_id="outside",
        parent_id=None,
        sibling_group="sg-outside",
        depth=0,
        role="session",
        session_name="outside-session",
        cwd="/tmp/outside",
    )

    _insert_run(
        db_path=db_path,
        run_id="run-root",
        agent_id="root",
        status="running",
        created_at="2026-01-01T00:00:00Z",
    )
    _insert_run(
        db_path=db_path,
        run_id="run-child",
        agent_id="child",
        status="completed",
        created_at="2026-01-01T00:00:01Z",
    )
    _insert_run(
        db_path=db_path,
        run_id="run-grandchild",
        agent_id="grandchild",
        status="failed",
        created_at="2026-01-01T00:00:02Z",
    )
    _insert_run(
        db_path=db_path,
        run_id="run-child-pending",
        agent_id="child",
        status="pending",
        created_at="2026-01-01T00:00:03Z",
    )
    _insert_run(
        db_path=db_path,
        run_id="run-outside",
        agent_id="outside",
        status="failed",
        created_at="2026-01-01T00:00:04Z",
    )

    result = store.get_run_summary("root")

    assert result["root_id"] == "root"
    assert result["counts"] == {
        "pending": 1,
        "running": 1,
        "completed": 1,
        "failed": 1,
        "total": 4,
    }
    agents = {agent["agent_handle"]: agent for agent in result["agents"]}
    assert set(agents) == {"child", "grandchild"}
    assert agents["child"]["status"] == "pending"
    assert agents["grandchild"]["status"] == "failed"


def test_get_run_summary_handles_cyclic_agent_relationships(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="child",
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="agent",
        session_name="child-agent",
        cwd="/tmp/child",
    )
    store.upsert_agent(
        agent_id="root",
        parent_id="child",
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )

    _insert_run(
        db_path=db_path,
        run_id="run-root",
        agent_id="root",
        status="running",
        created_at="2026-01-01T00:00:00Z",
    )
    _insert_run(
        db_path=db_path,
        run_id="run-child",
        agent_id="child",
        status="completed",
        created_at="2026-01-01T00:00:01Z",
    )

    result = store.get_run_summary("root")

    assert result["counts"] == {
        "pending": 0,
        "running": 1,
        "completed": 1,
        "failed": 0,
        "total": 2,
    }
    assert [agent["agent_handle"] for agent in result["agents"]] == ["child"]
    assert result["agents"][0]["status"] == "completed"


def test_get_run_summary_orders_agents_descending_and_respects_limit(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    for agent_id, created_at in [
        ("agent-old", "2026-01-01T00:00:00Z"),
        ("agent-mid", "2026-01-02T00:00:00Z"),
        ("agent-new", "2026-01-03T00:00:00Z"),
    ]:
        store.upsert_agent(
            agent_id=agent_id,
            parent_id="root",
            sibling_group=f"sg-{agent_id}",
            depth=1,
            role="agent",
            session_name=agent_id,
            cwd=f"/tmp/{agent_id}",
        )
        _insert_run(
            db_path=db_path,
            run_id=f"run-{agent_id}",
            agent_id=agent_id,
            status="running",
            created_at=created_at,
        )

    limited = store.get_run_summary("root", limit=2)
    assert [row["agent_handle"] for row in limited["agents"]] == ["agent-new", "agent-mid"]

    neg_limit = store.get_run_summary("root", limit=-5)
    assert neg_limit["agents"] == []
    assert neg_limit["counts"] == {
        "pending": 0,
        "running": 3,
        "completed": 0,
        "failed": 0,
        "total": 3,
    }


def test_get_run_summary_does_not_expose_spec_or_tokens(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="child",
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="agent",
        session_name="child-agent",
        cwd="/tmp/child",
    )
    _insert_run(
        db_path=db_path,
        run_id="run-sensitive",
        agent_id="child",
        status="completed",
        created_at="2026-01-01T00:00:00Z",
        spec_json='{"env": {"OPENAI_API_KEY": "secret"}}',
        report_token_hash="super-secret-token-hash",
        result="line one\nline two",
        error="x" * 200,
    )

    result = store.get_run_summary("root")

    assert len(result["agents"]) == 1
    summary_agent = result["agents"][0]
    assert set(summary_agent) == {
        "agent_handle",
        "agent_id_short",
        "agent_type",
        "model",
        "role",
        "session_name",
        "status",
        "result_preview",
        "error_preview",
        "exit_code",
        "created_at",
        "started_at",
        "ended_at",
        "task",
        "recent_activity",
        "skills",
    }
    assert summary_agent["agent_id_short"] == "child"
    assert summary_agent["model"] == "default"
    assert "run_id" not in summary_agent
    assert "agent_id" not in summary_agent
    assert "spec_json" not in summary_agent
    assert "report_token_hash" not in summary_agent
    assert "result" not in summary_agent
    assert "error" not in summary_agent
    assert summary_agent["result_preview"] == "line one line two"
    assert summary_agent["error_preview"].endswith("…")
    assert len(summary_agent["error_preview"]) == 160
    assert summary_agent["task"] is None
    assert summary_agent["recent_activity"] == []
    assert summary_agent["skills"] == []


def test_get_run_summary_projects_skills_from_tool_calls(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)
    _summary_agent(store)
    store.create_run(
        run_id="run-1",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={},
        report_token_hash="hash",
    )
    store.append_run_event(
        run_id="run-1",
        kind="tool_call",
        payload={"toolName": "skill", "skillName": "python-development", "snippet": "skill python-development"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="tool_call",
        payload={"toolName": "read", "snippet": "read pi-swarm/cli/src/basecamp.swarm/store.py"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="tool_call",
        payload={"toolName": "skill", "skillName": "sql", "snippet": "skill sql"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="tool_call",
        payload={"toolName": "skill", "skillName": "python-development", "snippet": "skill python-development"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="tool_call",
        payload={"toolName": "skill", "snippet": "skill marimo"},
    )
    with sqlite3.connect(db_path) as connection:
        for seq in range(1, 6):
            connection.execute(
                "UPDATE run_events SET ts = ? WHERE run_id = ? AND seq = ?",
                (f"2026-01-01T00:00:0{seq}Z", "run-1", seq),
            )

    result = store.get_run_summary("root")

    assert result["agents"][0]["skills"] == [
        {"name": "marimo", "count": 1, "last_seq": 5, "last_timestamp": "2026-01-01T00:00:05Z"},
        {
            "name": "python-development",
            "count": 2,
            "last_seq": 4,
            "last_timestamp": "2026-01-01T00:00:04Z",
        },
        {"name": "sql", "count": 1, "last_seq": 3, "last_timestamp": "2026-01-01T00:00:03Z"},
    ]


def test_get_run_summary_projects_safe_task_log_and_activity(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    task_dir = tmp_path / "tasks"
    store = Store(db_path=db_path, task_dir=task_dir)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="agent",
        session_name="child-agent",
        cwd="/tmp/child",
        model="claude-haiku-4-5",
    )
    store.create_run(
        run_id="run-1",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={"env": {"SECRET": "nope"}, "cwd": "/secret"},
        report_token_hash="secret-token-hash",
    )
    store.append_run_event(
        run_id="run-1",
        kind="tool_execution_start",
        payload={
            "toolName": "read\x1b[31m",
            "turnIndex": 2,
            "timestamp": "agent-supplied-timestamp",
            "args": {"path": "/secret"},
            "output": "private",
            "toolCallId": "call-secret",
            "cwd": "/secret",
            "env": {"TOKEN": "secret"},
            "error": "private",
        },
    )
    store.append_run_event(
        run_id="run-1",
        kind="tool_call",
        payload={
            "category": "tool",
            "label": "Read file",
            "snippet": "opening /safe/path",
            "toolName": "read",
            "toolCallId": "call-secret",
            "raw": {"args": "private"},
        },
    )
    store.append_run_event(
        run_id="run-1",
        kind="tool_result",
        payload={
            "category": "tool",
            "label": "Read file",
            "snippet": "done",
            "toolName": "read",
            "isError": False,
            "toolCallId": "call-secret",
            "output": "private output",
        },
    )
    store.append_run_event(
        run_id="run-1",
        kind="assistant_output",
        payload={
            "category": "assistant",
            "snippet": "safe answer",
            "text": "full safe answer",
            "message": "raw message",
        },
    )
    store.append_run_event(
        run_id="run-1",
        kind="thinking",
        payload={"category": "thinking", "snippet": "thinking…", "chainOfThought": "hidden"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="agent_result",
        payload={"category": "result", "label": "Completed", "snippet": "summary", "isError": True},
    )
    store.append_run_event(
        run_id="run-1",
        kind="turn_end",
        payload={"turnIndex": 3, "toolCount": 2, "raw": "private"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="raw_model_delta",
        payload={"toolName": "should-not-leak", "turnIndex": 4},
    )
    with sqlite3.connect(db_path) as connection:
        for seq in range(1, 9):
            connection.execute(
                "UPDATE run_events SET ts = ? WHERE run_id = ? AND seq = ?",
                (f"2026-01-01T00:00:0{seq - 1}Z", "run-1", seq),
            )
    _write_task_log(
        task_dir,
        "agent-1",
        [
            {
                "goal": "Ship \x1b[32mobservability\x1b[0m\x07",
                "active": True,
                "tasks": [
                    {"label": "Done", "description": "d", "criteria": "c", "notes": None, "status": "completed"},
                    {"label": 456, "description": "bad", "criteria": "bad", "notes": None, "status": "completed"},
                    {"label": 123, "description": "bad", "criteria": "bad", "notes": None, "status": "pending"},
                    {
                        "label": "Bad status",
                        "description": "bad",
                        "criteria": "bad",
                        "notes": None,
                        "status": "unknown",
                    },
                    "not-a-task",
                    {
                        "label": "Current\x1b]0;title\x07 task",
                        "description": "Desc\x00 with controls",
                        "criteria": "c",
                        "notes": "n" * 400,
                        "status": "active",
                    },
                    {"label": "Deleted", "description": "d", "criteria": "c", "notes": None, "status": "deleted"},
                    {"label": "Pending", "description": "d", "criteria": "c", "notes": None, "status": "pending"},
                ],
            }
        ],
    )

    result = store.get_run_summary("root")

    agent = result["agents"][0]
    assert "agent_id" not in agent
    assert "run_id" not in agent
    assert agent["agent_id_short"] == "agent1"
    assert agent["model"] == "claude-haiku-4-5"
    assert agent["task"] == {
        "goal": "Ship observability",
        "progress": {"completed": 1, "deleted": 1, "total": 3},
        "task_plan": [
            {"index": 0, "label": "Done", "status": "completed"},
            {"index": 5, "label": "Current task", "status": "active"},
            {"index": 7, "label": "Pending", "status": "pending"},
        ],
        "current_task": {
            "index": 5,
            "label": "Current task",
            "status": "active",
            "description": "Desc with controls",
            "notes": f"{'n' * 239}…",
        },
    }
    assert agent["recent_activity"] == [
        {
            "kind": "tool_execution_start",
            "seq": 1,
            "timestamp": "2026-01-01T00:00:00Z",
            "toolName": "read",
            "turnIndex": 2,
        },
        {
            "kind": "tool_call",
            "seq": 2,
            "timestamp": "2026-01-01T00:00:01Z",
            "category": "tool",
            "label": "Read file",
            "snippet": "opening /safe/path",
            "toolName": "read",
        },
        {
            "kind": "tool_result",
            "seq": 3,
            "timestamp": "2026-01-01T00:00:02Z",
            "category": "tool",
            "label": "Read file",
            "snippet": "done",
            "toolName": "read",
            "isError": False,
        },
        {
            "kind": "assistant_output",
            "seq": 4,
            "timestamp": "2026-01-01T00:00:03Z",
            "category": "assistant",
            "snippet": "safe answer",
        },
        {
            "kind": "thinking",
            "seq": 5,
            "timestamp": "2026-01-01T00:00:04Z",
            "category": "thinking",
            "snippet": "thinking…",
        },
        {
            "kind": "agent_result",
            "seq": 6,
            "timestamp": "2026-01-01T00:00:05Z",
            "category": "result",
            "label": "Completed",
            "snippet": "summary",
            "isError": True,
        },
        {
            "kind": "turn_end",
            "seq": 7,
            "timestamp": "2026-01-01T00:00:06Z",
            "turnIndex": 3,
            "toolCount": 2,
        },
    ]
    assert agent["recent_activity"][0]["timestamp"] != "agent-supplied-timestamp"
    assert all(activity["kind"] != "raw_model_delta" for activity in agent["recent_activity"])
    for activity in agent["recent_activity"]:
        assert all(
            key not in activity
            for key in [
                "args",
                "output",
                "toolCallId",
                "cwd",
                "env",
                "error",
                "payload",
                "raw",
                "message",
                "text",
                "chainOfThought",
            ]
        )


def test_get_run_messages_projects_selected_agent_latest_three_messages(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)
    _summary_agent(store)
    store.create_run(
        run_id="run-1",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={"env": {"SECRET": "nope"}},
        report_token_hash="hash",
    )
    store.append_run_event(
        run_id="run-1",
        kind="assistant_output",
        payload={"label": "assistant", "snippet": "one", "text": "one"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="tool_result",
        payload={"text": "tool output should not appear"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="assistant_output",
        payload={"label": "assistant", "snippet": "two", "text": "two"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="assistant_output",
        payload={"label": "assistant", "snippet": "three", "text": "\x1b[31mthree\x1b[0m\nline\x00"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="assistant_output",
        payload={"label": "assistant", "snippet": "four", "text": "four"},
    )
    store.set_run_result(run_id="run-1", status="completed", result="final\nanswer", error=None)

    with sqlite3.connect(db_path) as connection:
        for seq in range(1, 6):
            connection.execute(
                "UPDATE run_events SET ts = ? WHERE run_id = ? AND seq = ?",
                (f"2026-01-01T00:00:0{seq}Z", "run-1", seq),
            )
        connection.execute(
            "UPDATE runs SET ended_at = ? WHERE id = ?",
            ("2026-01-01T00:00:06Z", "run-1"),
        )

    result = store.get_run_messages("root", agent_handle="agent-1")

    assert result == {
        "root_id": "root",
        "agent_handle": "agent-1",
        "messages": [
            {
                "kind": "assistant_output",
                "seq": 4,
                "timestamp": "2026-01-01T00:00:04Z",
                "label": "assistant",
                "text": "three\nline",
            },
            {
                "kind": "assistant_output",
                "seq": 5,
                "timestamp": "2026-01-01T00:00:05Z",
                "label": "assistant",
                "text": "four",
            },
            {
                "kind": "agent_result",
                "seq": None,
                "timestamp": "2026-01-01T00:00:06Z",
                "label": "result",
                "text": "final\nanswer",
            },
        ],
    }
    for message in result["messages"]:
        assert set(message) == {"kind", "seq", "timestamp", "label", "text"}


def test_get_run_messages_deduplicates_terminal_result_and_validates_scope(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)
    _summary_agent(store)
    store.create_run(run_id="run-1", agent_id="agent-1", dispatcher_id="root", spec={}, report_token_hash="hash")
    store.append_run_event(
        run_id="run-1",
        kind="assistant_output",
        payload={"label": "assistant", "snippet": "same", "text": "same"},
    )
    store.set_run_result(run_id="run-1", status="completed", result="same", error=None)
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group="sg-outside",
        depth=0,
        role="session",
        session_name="outside-root",
        cwd="/tmp/outside",
    )
    store.upsert_agent(
        agent_id="outside-agent",
        parent_id="outside-root",
        sibling_group="sg-outside-child",
        depth=1,
        role="agent",
        session_name="outside-agent",
        cwd="/tmp/outside-agent",
    )
    store.create_run(
        run_id="run-outside",
        agent_id="outside-agent",
        dispatcher_id="outside-root",
        spec={},
        report_token_hash="hash",
    )
    store.append_run_event(
        run_id="run-outside",
        kind="assistant_output",
        payload={"label": "assistant", "snippet": "private", "text": "private outside text"},
    )

    scoped = store.get_run_messages("root", agent_handle="agent-1")
    outside = store.get_run_messages("root", agent_handle="outside-agent")

    assert [message["text"] for message in scoped["messages"]] == ["same"]
    assert outside == {"root_id": "root", "agent_handle": "outside-agent", "messages": []}


def test_get_run_summary_bounds_and_tolerates_malformed_activity(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)
    _summary_agent(store)
    store.create_run(
        run_id="run-1",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={},
        report_token_hash="hash",
    )

    for index in range(12):
        store.append_run_event(
            run_id="run-1",
            kind="tool_call",
            payload={"snippet": f"event {index + 1}", "isError": "bad" if index == 4 else False},
        )

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE run_events SET payload_json = ? WHERE run_id = ? AND seq = ?",
            ("{not-json", "run-1", 4),
        )
        for seq in range(1, 13):
            connection.execute(
                "UPDATE run_events SET ts = ? WHERE run_id = ? AND seq = ?",
                (f"2026-01-01T00:00:{seq:02d}Z", "run-1", seq),
            )

    activity = store.get_run_summary("root")["agents"][0]["recent_activity"]

    assert len(activity) == 10
    assert [item["seq"] for item in activity] == list(range(3, 13))
    malformed = activity[1]
    assert malformed == {
        "kind": "tool_call",
        "seq": 4,
        "timestamp": "2026-01-01T00:00:04Z",
    }
    non_bool_error = activity[2]
    assert non_bool_error["seq"] == 5
    assert non_bool_error["snippet"] == "event 5"
    assert "isError" not in non_bool_error


def test_get_run_summary_tolerates_malformed_task_logs(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    task_dir = tmp_path / "tasks"
    store = Store(db_path=db_path, task_dir=task_dir)
    _summary_agent(store)
    task_dir.mkdir()
    (task_dir / "agent-1.json").write_text("not json", encoding="utf-8")

    result = store.get_run_summary("root")

    assert result["agents"][0]["task"] is None


def test_get_run_summary_rejects_unsafe_task_log_paths_symlinks_and_size(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    task_dir = tmp_path / "tasks"
    store = Store(db_path=db_path, task_dir=task_dir)
    _summary_agent(store, agent_id="../escape")
    task_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps([{"goal": "bad", "active": True, "tasks": []}]), encoding="utf-8")
    (task_dir / "..%2Fescape.json").write_text("[]", encoding="utf-8")

    assert store.get_run_summary("root")["agents"][0]["task"] is None

    store = Store(db_path=tmp_path / "daemon2.db", task_dir=task_dir)
    _summary_agent(store, agent_id="agent-1")
    (task_dir / "agent-1.json").symlink_to(outside)
    assert store.get_run_summary("root")["agents"][0]["task"] is None

    (task_dir / "agent-1.json").unlink()
    (task_dir / "agent-1.json").write_text("[" + (" " * (256 * 1024)) + "]", encoding="utf-8")
    assert store.get_run_summary("root")["agents"][0]["task"] is None


def _create_workstream(
    store: Store,
    *,
    workstream_id: str = "ws-1",
    slug: str = "alpha",
    label: str = "Alpha",
    brief: str = "Do the thing",
    source_dossier_path: str = "/tmp/dossier.md",
    constraints: str | None = None,
    source_repo_page_path: str | None = None,
) -> None:
    store.create_workstream(
        workstream_id=workstream_id,
        slug=slug,
        label=label,
        brief=brief,
        source_dossier_path=source_dossier_path,
        constraints=constraints,
        source_repo_page_path=source_repo_page_path,
    )


def test_create_workstream_then_get_resolves_by_id_and_slug(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    _create_workstream(store, workstream_id="ws-1", slug="alpha")

    by_id = store.get_workstream("ws-1")
    by_slug = store.get_workstream("alpha")

    assert by_id is not None
    assert by_id["id"] == "ws-1"
    assert by_id["slug"] == "alpha"
    assert by_id["status"] == "open"
    assert by_id["label"] == "Alpha"
    assert by_id["brief"] == "Do the thing"
    assert by_id["source_dossier_path"] == "/tmp/dossier.md"
    assert by_id["constraints"] is None
    assert by_id["source_repo_page_path"] is None
    assert by_id["created_at"] is not None
    assert by_id["updated_at"] == by_id["created_at"]
    assert by_slug == by_id
    assert store.get_workstream("missing") is None


def test_create_workstream_duplicate_slug_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    _create_workstream(store, workstream_id="ws-1", slug="alpha")

    with pytest.raises(DuplicateWorkstreamSlugError):
        _create_workstream(store, workstream_id="ws-2", slug="alpha")


def test_list_workstreams_honors_status_dossier_query_and_repo(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    _create_workstream(store, workstream_id="ws-1", slug="alpha", label="Alpha")
    _create_workstream(
        store,
        workstream_id="ws-2",
        slug="beta",
        label="Beta Thing",
        source_dossier_path="/tmp/other.md",
    )

    # Attach an agent to ws-1 with a repo so the repo filter can find it.
    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.attach_workstream_agent(
        workstream_id="ws-1",
        agent_id="agent-1",
        repo="org/repo",
        now="2026-01-01T00:00:00Z",
    )

    # No filters: both workstreams returned, ordered by updated_at DESC.
    all_ws = store.list_workstreams()
    assert [row["id"] for row in all_ws] == ["ws-2", "ws-1"]
    assert all(row["agent_count"] is not None for row in all_ws)
    assert all_ws[0]["agent_count"] == 0
    assert all_ws[1]["agent_count"] == 1

    # Status filter.
    store.set_workstream_status(workstream_id="ws-1", status="closed", now="2026-01-02T00:00:00Z")
    closed = store.list_workstreams(status="closed")
    assert [row["id"] for row in closed] == ["ws-1"]

    open_ws = store.list_workstreams(status="open")
    assert [row["id"] for row in open_ws] == ["ws-2"]

    # Dossier path filter.
    by_dossier = store.list_workstreams(dossier_path="/tmp/other.md")
    assert [row["id"] for row in by_dossier] == ["ws-2"]

    # Query substring on slug and label (case-insensitive).
    by_slug_query = store.list_workstreams(query="alp")
    assert [row["id"] for row in by_slug_query] == ["ws-1"]

    by_label_query = store.list_workstreams(query="thing")
    assert [row["id"] for row in by_label_query] == ["ws-2"]

    # Repo filter: only workstreams with an attached agent whose repo matches.
    by_repo = store.list_workstreams(repo="org/repo")
    assert [row["id"] for row in by_repo] == ["ws-1"]

    by_repo_missing = store.list_workstreams(repo="other/repo")
    assert by_repo_missing == []


def test_attach_workstream_agent_appends_distinct_and_preserves_joined_at(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    _create_workstream(store, workstream_id="ws-1", slug="alpha")
    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.upsert_agent(
        agent_id="agent-2",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-b",
        cwd="/tmp/b",
    )

    store.attach_workstream_agent(
        workstream_id="ws-1",
        agent_id="agent-1",
        repo="org/repo",
        now="2026-01-01T00:00:00Z",
    )
    store.attach_workstream_agent(
        workstream_id="ws-1",
        agent_id="agent-2",
        repo="org/other",
        now="2026-01-01T00:00:01Z",
    )

    ws = store.get_workstream_with_agents("ws-1")
    assert ws is not None
    assert [agent["agent_id"] for agent in ws["agents"]] == ["agent-1", "agent-2"]
    assert ws["agents"][0]["joined_at"] == "2026-01-01T00:00:00Z"
    assert ws["agents"][1]["joined_at"] == "2026-01-01T00:00:01Z"

    # Re-attaching the same agent updates fields but does not duplicate and preserves joined_at.
    store.attach_workstream_agent(
        workstream_id="ws-1",
        agent_id="agent-1",
        repo="org/updated",
        worktree_label="wt-foo",
        status="failed",
        error="boom",
        now="2026-01-02T00:00:00Z",
    )

    ws = store.get_workstream_with_agents("ws-1")
    assert ws is not None
    assert [agent["agent_id"] for agent in ws["agents"]] == ["agent-1", "agent-2"]
    agent_1 = ws["agents"][0]
    assert agent_1["joined_at"] == "2026-01-01T00:00:00Z"
    assert agent_1["repo"] == "org/updated"
    assert agent_1["worktree_label"] == "wt-foo"
    assert agent_1["status"] == "failed"
    assert agent_1["error"] == "boom"


def test_attach_workstream_agent_missing_workstream_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)
    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )

    with pytest.raises(WorkstreamNotFoundError):
        store.attach_workstream_agent(workstream_id="ws-missing", agent_id="agent-1")


def test_get_workstream_with_agents_populates_run_status(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    _create_workstream(store, workstream_id="ws-1", slug="alpha")
    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.create_run(
        run_id="run-1",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={"task": "x"},
        report_token_hash="hash",
    )
    store.attach_workstream_agent(
        workstream_id="ws-1",
        agent_id="agent-1",
        repo="org/repo",
        now="2026-01-01T00:00:00Z",
    )

    ws = store.get_workstream_with_agents("ws-1")
    assert ws is not None
    assert len(ws["agents"]) == 1
    agent = ws["agents"][0]
    assert agent["agent_id"] == "agent-1"
    assert agent["agent_handle"] == "agent-1"
    assert agent["repo"] == "org/repo"
    assert agent["run_status"] == "running"

    store.set_run_result(run_id="run-1", status="completed", result="done", error=None)
    ws = store.get_workstream_with_agents("ws-1")
    assert ws is not None
    assert ws["agents"][0]["run_status"] == "completed"


def test_get_workstream_with_agents_missing_returns_none(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    assert store.get_workstream_with_agents("missing") is None


def test_set_workstream_status_flips_open_to_closed_and_rejects_invalid(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    _create_workstream(store, workstream_id="ws-1", slug="alpha")

    assert store.set_workstream_status(workstream_id="ws-1", status="closed", now="2026-01-02T00:00:00Z") is True
    ws = store.get_workstream("ws-1")
    assert ws is not None
    assert ws["status"] == "closed"
    assert ws["updated_at"] == "2026-01-02T00:00:00Z"

    assert store.set_workstream_status(workstream_id="ws-missing", status="closed") is False

    with pytest.raises(ValueError):
        store.set_workstream_status(workstream_id="ws-1", status="bogus")


def _create_message(store: Store, message_id: str) -> None:
    store.create_message(
        message_id=message_id,
        root_id="root-1",
        sender_node_id="sender-1",
        sender_handle="sender-handle",
        target_agent_id="target-1",
        target_handle="target-handle",
        content="hello peer",
        interrupt=False,
    )


def _unknown_message_status(message_id: str) -> dict[str, object]:
    return {
        "message_id": message_id,
        "status": "unknown",
        "error": None,
        "created_at": None,
        "sent_at": None,
        "queued_at": None,
        "failed_at": None,
    }


def _summary_agent(store: Store, *, agent_id: str = "agent-1") -> None:
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id=agent_id,
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="agent",
        session_name="child-agent",
        cwd="/tmp/child",
    )


def _write_task_log(task_dir: Path, agent_id: str, cycles: list[dict[str, object]]) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / f"{agent_id}.json").write_text(json.dumps(cycles), encoding="utf-8")


def _insert_run(
    *,
    db_path: Path,
    run_id: str,
    agent_id: str,
    status: str,
    created_at: str,
    spec_json: str = "{}",
    report_token_hash: str | None = None,
    result: str | None = None,
    error: str | None = None,
    exit_code: int | None = None,
) -> None:
    started_at = created_at
    ended_at = created_at if status in {"completed", "failed"} else None

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO runs (
                id,
                agent_id,
                status,
                spec_json,
                report_token_hash,
                result,
                error,
                exit_code,
                created_at,
                started_at,
                ended_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                agent_id,
                status,
                spec_json,
                report_token_hash,
                result,
                error,
                exit_code,
                created_at,
                started_at,
                ended_at,
            ),
        )
        connection.execute(
            "UPDATE agents SET current_run_id = ? WHERE id = ?",
            (run_id, agent_id),
        )
