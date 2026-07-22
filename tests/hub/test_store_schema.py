"""Tests for daemon store schema initialization and column migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from basecamp.hub.store import Store


def test_store_initializes_required_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    Store(db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        indexes = {row[1]: row for row in connection.execute("PRAGMA index_list(agents)").fetchall()}

    table_names = {row[0] for row in rows}
    assert "agents" in table_names
    assert "runs" in table_names
    assert "run_events" in table_names
    assert "messages" in table_names
    assert "workstreams" in table_names
    assert "workstream_versions" in table_names
    assert "workstream_agents" in table_names
    assert "analysis" not in table_names
    assert "raw_pi_thread" not in table_names
    assert "raw_pi_thread_node" not in table_names
    assert indexes["idx_agents_parent_id"][2] == 0


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


def test_store_adds_parent_index_to_existing_agents_table(tmp_path: Path) -> None:
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
                model TEXT
            )
            """
        )

    Store(db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        indexes = {row[1]: row for row in connection.execute("PRAGMA index_list(agents)").fetchall()}

    assert indexes["idx_agents_parent_id"][2] == 0


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


def test_store_remaps_legacy_role_values(tmp_path: Path) -> None:
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
                agent_handle TEXT
            )
            """
        )
        connection.executemany(
            "INSERT INTO agents (id, role, session_name, cwd, agent_handle) VALUES (?, ?, ?, '/tmp', ?)",
            [
                ("legacy-session", "session", "s", "handle-session"),
                ("legacy-agent", "agent", "a", "handle-agent"),
            ],
        )

    Store(db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        roles = dict(connection.execute("SELECT id, role FROM agents").fetchall())
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]

    # session -> agent (user-facing), agent -> worker (backgrounded). Single-pass:
    # a former 'session' now reading 'agent' must NOT be re-mapped on to 'worker'.
    assert roles == {"legacy-session": "agent", "legacy-agent": "worker"}
    assert user_version == 1


def test_store_drops_retired_columns_on_modern_sqlite(tmp_path: Path) -> None:
    if sqlite3.sqlite_version_info < (3, 35, 0):
        pytest.skip("ALTER TABLE ... DROP COLUMN requires SQLite 3.35+")

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
                product_role TEXT,
                run_kind TEXT,
                model TEXT
            )
            """
        )

    Store(db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agents)").fetchall()}

    assert "product_role" not in columns
    assert "run_kind" not in columns
    assert {"repo", "worktree_label", "branch", "agent_mode"} <= columns
