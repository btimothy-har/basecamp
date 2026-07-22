"""Tests for the compact active-agent run summary."""

from __future__ import annotations

from pathlib import Path

from store_helpers import _insert_run, _write_task_log

from basecamp.hub.store import Store


def _root(store: Store) -> None:
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="agent",
        session_name="root-session",
        cwd="/tmp/root",
    )


def _child(store: Store, agent_id: str, *, parent_id: str = "root") -> None:
    store.upsert_agent(
        agent_id=agent_id,
        parent_id=parent_id,
        sibling_group=f"sg-{agent_id}",
        depth=1,
        role="worker",
        session_name=f"{agent_id}-session",
        cwd=f"/tmp/{agent_id}",
        agent_type="worker",
    )


def test_get_run_summary_unknown_root_returns_empty_agents(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    assert store.get_run_summary("does-not-exist") == {"agents": []}


def test_get_run_summary_scopes_to_descendants_and_handles_cycles(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)
    _root(store)
    _child(store, "child")
    _child(store, "grandchild", parent_id="child")
    _child(store, "outside", parent_id="outside-root")

    _insert_run(
        db_path=db_path,
        run_id="run-child",
        agent_id="child",
        status="running",
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
        run_id="run-outside",
        agent_id="outside",
        status="running",
        created_at="2026-01-01T00:00:03Z",
    )
    store.upsert_agent(
        agent_id="root",
        parent_id="grandchild",
        sibling_group="sg-root",
        depth=0,
        role="agent",
        session_name="root-session",
        cwd="/tmp/root",
    )

    agents = {agent["agent_handle"]: agent for agent in store.get_run_summary("root")["agents"]}

    assert set(agents) == {"child", "grandchild"}
    assert agents["child"]["status"] == "running"
    assert agents["grandchild"]["status"] == "failed"


def test_get_run_summary_orders_agents_and_clamps_limit(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)
    _root(store)
    for agent_id, created_at in [
        ("agent-old", "2026-01-01T00:00:00Z"),
        ("agent-mid", "2026-01-02T00:00:00Z"),
        ("agent-new", "2026-01-03T00:00:00Z"),
    ]:
        _child(store, agent_id)
        _insert_run(
            db_path=db_path,
            run_id=f"run-{agent_id}",
            agent_id=agent_id,
            status="running",
            created_at=created_at,
        )

    limited = store.get_run_summary("root", limit=2)
    negative = store.get_run_summary("root", limit=-5)

    assert [agent["agent_handle"] for agent in limited["agents"]] == ["agent-new", "agent-mid"]
    assert negative == {"agents": []}


def test_get_run_summary_returns_only_widget_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    task_dir = tmp_path / "tasks"
    store = Store(db_path=db_path, task_dir=task_dir)
    _root(store)
    _child(store, "child")
    _insert_run(
        db_path=db_path,
        run_id="run-sensitive",
        agent_id="child",
        status="running",
        created_at="2026-01-01T00:00:00Z",
        spec_json='{"env": {"OPENAI_API_KEY": "secret"}}',
        report_token_hash="super-secret-token-hash",
        result="private result",
        error="private error",
    )
    _write_task_log(
        task_dir,
        "child",
        [
            {
                "goal": "Ship widget summary",
                "active": True,
                "tasks": [
                    {"label": "Done", "status": "completed"},
                    {"label": "Current", "description": "private detail", "status": "active"},
                ],
            }
        ],
    )

    [agent] = store.get_run_summary("root")["agents"]

    assert agent == {
        "agent_handle": "child",
        "agent_type": "worker",
        "session_name": "child-session",
        "status": "running",
        "created_at": "2026-01-01T00:00:00Z",
        "started_at": "2026-01-01T00:00:00Z",
        "task": {"goal": "Ship widget summary", "current_task": {"label": "Current"}},
    }
