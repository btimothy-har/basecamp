"""Shared factories for daemon store tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from basecamp.hub.store import Store


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
        role="agent",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id=agent_id,
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="worker",
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
