"""Run-wait projection, wait results, and waiter wake-ups."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Literal

from ...frames import WaitFrame, WaitResultItem
from ...registry import Registry, Waiter
from ...store import Store

TERMINAL_RUN_STATUSES = {"completed", "failed"}


def _normalize_wait_status(status: str) -> str:
    if status in TERMINAL_RUN_STATUSES:
        return status
    return "running"


def _wait_result_item(
    *,
    status: Literal["completed", "failed", "running", "unknown"],
    agent_id: str | None = None,
    agent_handle: str | None = None,
    result: str | None = None,
    error: str | None = None,
) -> WaitResultItem:
    values: dict[str, Any] = {"status": status, "result": result, "error": error}
    if agent_id is not None:
        values["agent_id"] = agent_id
    if agent_handle is not None:
        values["agent_handle"] = agent_handle
    return WaitResultItem(**values)


def _row_unknown_result(*, agent_id: str | None = None, agent_handle: str | None = None) -> WaitResultItem:
    return _wait_result_item(agent_id=agent_id, agent_handle=agent_handle, status="unknown")


def _wait_item_for_row(*, row: dict[str, Any], agent_id: str | None, agent_handle: str | None) -> WaitResultItem:
    status = row.get("status")
    if not isinstance(status, str):
        return _row_unknown_result(agent_id=agent_id, agent_handle=agent_handle)

    wait_status = _normalize_wait_status(status)
    if wait_status in TERMINAL_RUN_STATUSES:
        return _wait_result_item(
            agent_id=agent_id,
            agent_handle=agent_handle,
            status=wait_status,
            result=row.get("result"),
            error=row.get("error"),
        )

    return _wait_result_item(agent_id=agent_id, agent_handle=agent_handle, status="running")


def build_wait_results(
    *,
    agent_ids: list[str],
    agent_handles: list[str],
    rows_by_id: list[dict[str, Any]],
    rows_by_handle: list[dict[str, Any]],
) -> list[WaitResultItem]:
    by_id = {row["agent_id"]: row for row in rows_by_id if isinstance(row.get("agent_id"), str)}
    by_handle = {row["agent_handle"]: row for row in rows_by_handle if isinstance(row.get("agent_handle"), str)}
    ordered: list[WaitResultItem] = []

    for agent_id in agent_ids:
        row = by_id.get(agent_id)
        if row is None:
            ordered.append(_row_unknown_result(agent_id=agent_id))
            continue
        if not isinstance(row.get("status"), str):
            ordered.append(_row_unknown_result(agent_id=agent_id))
            continue
        ordered.append(_wait_item_for_row(row=row, agent_id=agent_id, agent_handle=None))

    for agent_handle in agent_handles:
        row = by_handle.get(agent_handle)
        if row is None:
            ordered.append(_row_unknown_result(agent_handle=agent_handle))
            continue
        if not isinstance(row.get("status"), str):
            ordered.append(_row_unknown_result(agent_handle=agent_handle))
            continue
        row_agent_id = row.get("agent_id") if isinstance(row.get("agent_id"), str) else None
        ordered.append(_wait_item_for_row(row=row, agent_id=row_agent_id, agent_handle=agent_handle))

    return ordered


async def build_wait_projection(
    *,
    agent_ids: list[str],
    agent_handles: list[str],
    store: Store,
    requester_node_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows_by_id = await asyncio.to_thread(
        store.get_agents_current_runs,
        agent_ids,
        dispatcher_id=requester_node_id,
    )
    rows_by_handle = await asyncio.to_thread(
        store.get_agents_current_runs_by_handles,
        agent_handles,
        dispatcher_id=requester_node_id,
    )
    return rows_by_id, rows_by_handle


def wait_target_run_ids(*, rows: list[dict[str, Any]]) -> set[str]:
    targets: set[str] = set()
    for row in rows:
        status = row.get("status")
        if not isinstance(status, str):
            continue
        run_id = row.get("run_id")
        if not isinstance(run_id, str):
            continue
        if _normalize_wait_status(status) not in TERMINAL_RUN_STATUSES:
            targets.add(run_id)
    return targets


async def wait_for_agents(
    *,
    frame: WaitFrame,
    store: Store,
    registry: Registry,
    requester_node_id: str,
) -> list[WaitResultItem]:
    agent_ids = list(dict.fromkeys(frame.agent_ids))
    agent_handles = list(dict.fromkeys(frame.agent_handles))
    rows_by_id, rows_by_handle = await build_wait_projection(
        agent_ids=agent_ids,
        agent_handles=agent_handles,
        store=store,
        requester_node_id=requester_node_id,
    )
    run_ids_to_wait = wait_target_run_ids(rows=[*rows_by_id, *rows_by_handle])

    if run_ids_to_wait:
        waiter = Waiter(
            waiter_id=str(uuid.uuid4()),
            run_ids=run_ids_to_wait,
            future=asyncio.get_running_loop().create_future(),
        )
        registry.add_waiter(waiter)
        try:
            await asyncio.wait_for(waiter.future, timeout=frame.timeout_s)
        except TimeoutError:
            pass
        finally:
            registry.remove_waiter(waiter.waiter_id)

    rows_by_id, rows_by_handle = await build_wait_projection(
        agent_ids=agent_ids,
        agent_handles=agent_handles,
        store=store,
        requester_node_id=requester_node_id,
    )
    return build_wait_results(
        agent_ids=agent_ids,
        agent_handles=agent_handles,
        rows_by_id=rows_by_id,
        rows_by_handle=rows_by_handle,
    )


async def notify_run_finalized(run_id: str, *, registry: Registry, store: Store) -> None:
    waiters = [waiter for waiter in registry.list_waiters() if not waiter.future.done() and run_id in waiter.run_ids]
    if not waiters:
        return

    run_ids = list({waiter_run_id for waiter in waiters for waiter_run_id in waiter.run_ids})
    terminal_rows = await asyncio.to_thread(store.get_run_wait_results, run_ids, terminal_only=True)
    terminal_run_ids = {row["run_id"] for row in terminal_rows if isinstance(row.get("run_id"), str)}

    for waiter in waiters:
        if waiter.run_ids.issubset(terminal_run_ids) and not waiter.future.done():
            waiter.future.set_result(None)
