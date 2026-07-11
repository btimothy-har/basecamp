"""Tests for daemon store task-log, activity, and skills projections."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from store_helpers import _summary_agent, _write_task_log

from basecamp.hub.store import Store


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
        payload={"toolName": "read", "snippet": "read pi-swarm/cli/src/basecamp.hub/store.py"},
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
