"""Tests for daemon store run summary scope, counts, ordering, and exposure."""

from __future__ import annotations

from pathlib import Path

from store_helpers import _insert_run

from basecamp.hub.store import Store


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
