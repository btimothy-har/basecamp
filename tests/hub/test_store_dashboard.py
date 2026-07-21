"""Tests for the global dashboard root, topology, stage, and privacy projection."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from store_helpers import _create_workstream, _insert_run, _write_task_log

from basecamp.hub.store import Store
from basecamp.hub.store.dashboard import DASHBOARD_AGENT_LIMIT

NOW = datetime(2026, 7, 21, 12, tzinfo=UTC)


def _root(
    store: Store,
    root_id: str,
    *,
    handle: str | None = None,
    mode: str | None = "work",
    depth: int = 0,
    role: str = "agent",
) -> None:
    store.upsert_agent(
        agent_id=root_id,
        agent_handle=handle or root_id,
        parent_id=None,
        sibling_group=None,
        depth=depth,
        role=role,
        session_name=f"session {root_id}",
        cwd=f"/private/{root_id}",
        repo="acme/widgets",
        worktree_label=f"wt/{root_id}",
        branch=f"bt/{root_id}",
        model="gpt-5.6",
        agent_mode=mode,
    )


def _agent(
    store: Store,
    agent_id: str,
    *,
    parent_id: str,
    handle: str | None = None,
    agent_type: str = "scout",
    depth: int = 1,
) -> None:
    store.upsert_agent(
        agent_id=agent_id,
        agent_handle=handle or agent_id,
        parent_id=parent_id,
        sibling_group=parent_id,
        depth=depth,
        role="worker",
        session_name=f"session {agent_id}",
        cwd=f"/private/{agent_id}",
        agent_type=agent_type,
        model="gpt-5.6-mini",
    )


def _set_last_seen(db_path: Path, agent_id: str, timestamp: str) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE agents SET last_seen_at = ? WHERE id = ?", (timestamp, agent_id))


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_all_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value), set())
    return set()


def test_dashboard_selects_structural_live_and_recent_roots_and_classifies_kind(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db", task_dir=tmp_path / "tasks")
    _root(store, "live-old", handle="live-root")
    _root(store, "recent", handle="recent-root")
    _root(store, "copilot", handle="copilot-root", mode="copilot")
    _root(store, "expired", handle="expired-root")
    _root(store, "wrong-depth", depth=1)
    _root(store, "wrong-role", role="worker")
    _set_last_seen(store.db_path, "live-old", "2026-07-16T00:00:00+00:00")
    _set_last_seen(store.db_path, "recent", "2026-07-21T10:00:00+00:00")
    _set_last_seen(store.db_path, "copilot", "2026-07-21T09:00:00+00:00")
    _set_last_seen(store.db_path, "expired", "2026-07-18T10:00:00+00:00")
    _create_workstream(store, workstream_id="ws-recent", slug="recent-workstream")
    _create_workstream(store, workstream_id="ws-copilot", slug="copilot-workstream")
    store.attach_workstream_agent(workstream_id="ws-recent", agent_id="recent")
    store.attach_workstream_agent(workstream_id="ws-copilot", agent_id="copilot")

    snapshot = store.get_dashboard_snapshot(live_node_ids={"live-old"}, now=NOW)

    assert [root["root_handle"] for root in snapshot["roots"]] == ["live-root", "recent-root", "copilot-root"]
    roots = {root["root_handle"]: root for root in snapshot["roots"]}
    assert roots["live-root"]["live"] is True
    assert roots["live-root"]["kind"] == "root"
    assert roots["recent-root"]["kind"] == "workstream"
    assert roots["copilot-root"]["kind"] == "copilot"
    assert all(root["agent_count"] == 0 for root in roots.values())
    assert snapshot["window_hours"] == 72


def test_dashboard_projects_recursive_topology_and_excludes_ask_subtrees(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db", task_dir=tmp_path / "tasks")
    _root(store, "root", handle="root-handle")
    _agent(store, "child", parent_id="root", handle="child-handle")
    _agent(store, "grandchild", parent_id="child", handle="grandchild-handle", depth=2)
    _agent(store, "ask", parent_id="root", agent_type="ask")
    _agent(store, "ask-child", parent_id="ask", depth=2)
    _root(store, "outside", handle="outside-root")
    _agent(store, "cycle-a", parent_id="cycle-b")
    _agent(store, "cycle-b", parent_id="cycle-a")
    _insert_run(
        db_path=store.db_path,
        run_id="run-child",
        agent_id="child",
        status="running",
        created_at="2026-07-21T10:00:00+00:00",
        result="still working",
    )
    _insert_run(
        db_path=store.db_path,
        run_id="run-grandchild",
        agent_id="grandchild",
        status="failed",
        created_at="2026-07-21T10:01:00+00:00",
        error="bounded failure",
    )
    store.append_run_event(run_id="run-child", kind="thinking", payload={"snippet": "hidden reasoning"})
    store.append_run_event(
        run_id="run-child",
        kind="tool_call",
        payload={"category": "read", "label": "Read source", "snippet": "Mapped the call path"},
    )

    snapshot = store.get_dashboard_snapshot(now=NOW)
    root = next(item for item in snapshot["roots"] if item["root_handle"] == "root-handle")
    agents = {agent["agent_handle"]: agent for agent in root["agents"]}

    assert set(agents) == {"child-handle", "grandchild-handle"}
    assert agents["child-handle"]["parent_handle"] == "root-handle"
    assert agents["child-handle"]["depth"] == 1
    assert agents["child-handle"]["status"] == "running"
    assert [event["kind"] for event in agents["child-handle"]["recent_activity"]] == ["tool_call"]
    assert agents["grandchild-handle"]["parent_handle"] == "child-handle"
    assert agents["grandchild-handle"]["depth"] == 2
    assert agents["grandchild-handle"]["status"] == "failed"
    assert root["agent_count"] == 2


def test_dashboard_reports_agent_truncation(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db", task_dir=tmp_path / "tasks")
    _root(store, "root")
    for index in range(DASHBOARD_AGENT_LIMIT + 1):
        _agent(store, f"agent-{index:03}", parent_id="root")

    root = store.get_dashboard_snapshot(now=NOW)["roots"][0]

    assert root["agent_count"] == DASHBOARD_AGENT_LIMIT + 1
    assert len(root["agents"]) == DASHBOARD_AGENT_LIMIT
    assert root["agents_truncated"] is True


def test_dashboard_projects_last_ten_goal_stages_with_bounded_tasks(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db", task_dir=tmp_path / "tasks")
    _root(store, "root")
    cycles: list[dict[str, object]] = [
        {
            "goal": f"Goal stage {stage_index}",
            "active": stage_index == 11,
            "archivedAt": None if stage_index == 11 else f"2026-07-{stage_index + 1:02}T00:00:00Z",
            "agentMode": "work",
            "planRef": {"context": "must remain private"},
            "tasks": [
                {
                    "label": f"Task {task_index}",
                    "description": f"Description {task_index}",
                    "criteria": f"Criteria {task_index}",
                    "status": "active" if stage_index == 11 and task_index == 0 else "pending",
                }
                for task_index in range(22)
            ],
        }
        for stage_index in range(12)
    ]
    _write_task_log(store.task_dir, "root", cycles)

    root = store.get_dashboard_snapshot(now=NOW)["roots"][0]

    assert root["stage_count"] == 12
    assert root["stages_truncated"] is True
    assert [stage["index"] for stage in root["stages"]] == list(range(2, 12))
    assert root["stages"][-1]["active"] is True
    assert len(root["stages"][-1]["tasks"]) == 20
    assert root["stages"][-1]["tasks_truncated"] is True
    assert root["stages"][-1]["tasks"][0]["description"] == "Description 0"
    assert root["task"]["current_task"]["label"] == "Task 0"


def test_dashboard_payload_omits_private_ids_paths_specs_and_raw_events(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db", task_dir=tmp_path / "tasks")
    _root(store, "private-root", handle="public-root")
    _agent(store, "private-agent", parent_id="private-root", handle="public-agent")
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE agents SET session_file = ? WHERE id IN (?, ?)",
            ("/Users/secret/session.jsonl", "private-root", "private-agent"),
        )
    store.create_run(
        run_id="private-run",
        agent_id="private-agent",
        dispatcher_id="private-root",
        spec={"prompt": "PROMPT_SECRET", "env": {"API_KEY": "ENV_SECRET"}},
        report_token_hash="TOKEN_SECRET",
    )
    store.set_run_result(
        run_id="private-run",
        status="failed",
        result=f"safe prefix {'x' * 300} RESULT_SECRET_TAIL",
        error=f"safe error {'x' * 300} ERROR_SECRET_TAIL",
    )
    store.append_run_event(
        run_id="private-run",
        kind="tool_call",
        payload={"label": "safe label", "raw": "RAW_SECRET", "env": "EVENT_ENV_SECRET"},
    )
    store.append_run_event(
        run_id="private-run",
        kind="thinking",
        payload={"snippet": "THINKING_SECRET"},
    )
    _write_task_log(
        store.task_dir,
        "private-root",
        [{"goal": "Safe goal", "active": True, "planRef": {"design": "PLAN_SECRET"}, "tasks": []}],
    )

    snapshot = store.get_dashboard_snapshot(now=NOW)
    serialized = json.dumps(snapshot)
    keys = _all_keys(snapshot)

    assert {
        "id",
        "root_id",
        "node_id",
        "agent_id",
        "run_id",
        "cwd",
        "session_file",
        "spec_json",
        "report_token_hash",
        "prompt",
        "env",
        "payload_json",
        "planRef",
        "thinking",
    }.isdisjoint(keys)
    for secret in (
        "/Users/secret",
        "PROMPT_SECRET",
        "ENV_SECRET",
        "TOKEN_SECRET",
        "RAW_SECRET",
        "EVENT_ENV_SECRET",
        "RESULT_SECRET_TAIL",
        "ERROR_SECRET_TAIL",
        "THINKING_SECRET",
        "PLAN_SECRET",
    ):
        assert secret not in serialized
