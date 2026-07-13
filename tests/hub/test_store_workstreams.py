"""Tests for daemon store workstream persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from store_helpers import _create_workstream

from basecamp.hub.store import (
    DuplicateWorkstreamSlugError,
    Store,
    WorkstreamNotFoundError,
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


def test_create_workstream_seeds_version_one(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    _create_workstream(store, workstream_id="ws-1", slug="alpha")

    ws = store.get_workstream("ws-1")
    assert ws is not None
    assert ws["version"] == 1

    detail = store.get_workstream_with_agents("ws-1")
    assert detail is not None
    assert [v["version"] for v in detail["versions"]] == [1]
    assert detail["versions"][0]["brief"] == "Do the thing"


def test_revise_workstream_bumps_version_and_retains_history(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    _create_workstream(store, workstream_id="ws-1", slug="alpha", label="Alpha", brief="Do the thing")

    new_version = store.revise_workstream(
        workstream_id="ws-1",
        label="Alpha v2",
        brief="Do the refined thing",
        constraints="stay in scope",
        now="2026-02-02T00:00:00Z",
    )
    assert new_version == 2

    ws = store.get_workstream("ws-1")
    assert ws is not None
    assert ws["version"] == 2
    assert ws["label"] == "Alpha v2"
    assert ws["brief"] == "Do the refined thing"
    assert ws["constraints"] == "stay in scope"
    assert ws["updated_at"] == "2026-02-02T00:00:00Z"
    # Identity and source pointers are stable across revisions.
    assert ws["slug"] == "alpha"
    assert ws["source_dossier_path"] == "/tmp/dossier.md"

    detail = store.get_workstream_with_agents("ws-1")
    assert detail is not None
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    # The old version content is retained verbatim.
    old = detail["versions"][1]
    assert old["version"] == 1
    assert old["label"] == "Alpha"
    assert old["brief"] == "Do the thing"
    assert old["constraints"] is None


def test_revise_workstream_missing_raises(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    with pytest.raises(WorkstreamNotFoundError):
        store.revise_workstream(workstream_id="ws-missing", label="x", brief="y")


def test_list_workstream_versions_by_id_and_slug(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    _create_workstream(store, workstream_id="ws-1", slug="alpha")
    store.revise_workstream(workstream_id="ws-1", label="Alpha v2", brief="v2 brief")

    by_id = store.list_workstream_versions("ws-1")
    by_slug = store.list_workstream_versions("alpha")
    assert by_id == by_slug
    assert by_id is not None
    assert [v["version"] for v in by_id] == [2, 1]
    assert store.list_workstream_versions("missing") is None


def test_workstreams_version_backfill_migrates_legacy_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    # Build a pre-versioning workstreams table (no version column, no history table).
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE workstreams (
                id TEXT PRIMARY KEY,
                slug TEXT UNIQUE NOT NULL,
                label TEXT NOT NULL,
                brief TEXT NOT NULL,
                constraints TEXT,
                source_dossier_path TEXT NOT NULL,
                source_repo_page_path TEXT,
                status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO workstreams (id, slug, label, brief, source_dossier_path, status, created_at, updated_at)
            VALUES ('ws-legacy', 'legacy', 'Legacy', 'legacy brief', '/tmp/d.md', 'open', 't0', 't1')
            """
        )

    store = Store(db_path=db_path)

    ws = store.get_workstream("ws-legacy")
    assert ws is not None
    assert ws["version"] == 1

    versions = store.list_workstream_versions("ws-legacy")
    assert versions is not None
    assert [v["version"] for v in versions] == [1]
    assert versions[0]["brief"] == "legacy brief"
    # The v1 snapshot's created_at is seeded from the workstream's created_at, not updated_at.
    assert versions[0]["created_at"] == "t0"

    # Re-opening the store does not double-seed the backfill.
    Store(db_path=db_path)
    versions_again = store.list_workstream_versions("ws-legacy")
    assert versions_again is not None
    assert [v["version"] for v in versions_again] == [1]


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
        role="worker",
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
        role="worker",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.upsert_agent(
        agent_id="agent-2",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="worker",
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
        role="worker",
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
        role="worker",
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
