"""Daemon orchestration services independent of HTTP/WebSocket transport."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from .frames import (
    DispatchFrame,
    ListAgentItem,
    ListAgentsFrame,
    ResultReportFrame,
    TelemetryFrame,
    WaitFrame,
    WaitResultItem,
)
from .process import reap_agent_process, spawn_agent_process
from .registry import Registry, Waiter
from .store import ActiveRunExistsError, DuplicateAgentHandleError, Store

_REDACTED_ENV_VALUE = "<redacted>"

DEFAULT_AGENT_MAX_DEPTH = 2
TERMINAL_RUN_STATUSES = {"completed", "failed"}

DispatchAckStatus = Literal["spawned", "rejected"]
DispatchAckReason = Literal[
    "depth_cap",
    "active_run_exists",
    "duplicate_agent_handle",
    "agent_type_mismatch",
    "spawn_failed",
]
DispatchRejectionReason = Literal["depth_cap", "active_run_exists", "duplicate_agent_handle", "agent_type_mismatch"]


@dataclass(frozen=True)
class DispatchAck:
    status: DispatchAckStatus
    reason: DispatchAckReason | None


@dataclass(frozen=True)
class PreparedDispatch:
    agent_id: str
    report_token: str
    child_depth: int


@dataclass(frozen=True)
class DispatchRejection:
    reason: DispatchRejectionReason


def _sanitize_dispatch_spec(spec: dict[str, Any]) -> dict[str, Any]:
    env = spec.get("env")
    if isinstance(env, dict):
        env_keys = [str(key) for key in env.keys()]
        spec = dict(spec)
        spec["env"] = dict.fromkeys(env_keys, _REDACTED_ENV_VALUE)
        spec["env_keys"] = env_keys
    return spec


def _generate_report_token() -> str:
    return secrets.token_urlsafe(32)


def _hash_report_token(report_token: str) -> str:
    return hashlib.sha256(report_token.encode("utf-8")).hexdigest()


def _metadata_mismatches(*, existing: dict[str, Any], frame: DispatchFrame) -> bool:
    existing_agent_type = existing.get("agent_type")
    if isinstance(existing_agent_type, str) and frame.agent_type and existing_agent_type != frame.agent_type:
        return True

    existing_run_kind = existing.get("run_kind")
    return bool(isinstance(existing_run_kind, str) and frame.run_kind and existing_run_kind != frame.run_kind)


def _resolve_agent_max_depth() -> int:
    raw = os.getenv("BASECAMP_AGENT_MAX_DEPTH")
    try:
        value = int(raw) if raw is not None else DEFAULT_AGENT_MAX_DEPTH
    except ValueError:
        return DEFAULT_AGENT_MAX_DEPTH
    return value if value >= 0 else DEFAULT_AGENT_MAX_DEPTH


async def prepare_dispatch(
    *,
    frame: DispatchFrame,
    dispatcher_node_id: str,
    store: Store,
) -> PreparedDispatch | DispatchRejection:
    dispatcher = await asyncio.to_thread(store.get_agent, dispatcher_node_id)
    dispatcher_depth = int(dispatcher.get("depth", 0)) if dispatcher else 0
    existing_agent = None
    if frame.agent_handle:
        existing_agent = await asyncio.to_thread(store.get_agent_by_handle, frame.agent_handle)

    if existing_agent is not None:
        existing_agent_id = str(existing_agent.get("id"))
        requester_root = await asyncio.to_thread(store.resolve_agent_root, dispatcher_node_id)
        existing_agent_root = await asyncio.to_thread(store.resolve_agent_root, existing_agent_id)
        if requester_root is None or existing_agent_root != requester_root:
            return DispatchRejection(reason="duplicate_agent_handle")
        if frame.agent_id and frame.agent_id != existing_agent_id:
            return DispatchRejection(reason="duplicate_agent_handle")
        if _metadata_mismatches(existing=existing_agent, frame=frame):
            return DispatchRejection(reason="agent_type_mismatch")
        agent_id = existing_agent_id
        child_depth = int(existing_agent.get("depth", dispatcher_depth + 1))
    else:
        agent_id = frame.agent_id or str(uuid.uuid4())
        child_depth = dispatcher_depth + 1

    max_depth = _resolve_agent_max_depth()
    if child_depth > max_depth:
        return DispatchRejection(reason="depth_cap")

    report_token = _generate_report_token()
    report_token_hash = _hash_report_token(report_token)
    spec_json = _sanitize_dispatch_spec(frame.spec.model_dump(mode="json"))
    try:
        if existing_agent is None:
            await asyncio.to_thread(
                store.upsert_agent,
                agent_id=agent_id,
                parent_id=dispatcher_node_id,
                sibling_group=None,
                depth=child_depth,
                role="agent",
                session_name=frame.agent_handle or agent_id,
                cwd=frame.spec.cwd,
                agent_handle=frame.agent_handle,
                agent_type=frame.agent_type,
                run_kind=frame.run_kind,
                model=frame.model or "default",
            )
        else:
            await asyncio.to_thread(
                store.upsert_agent,
                agent_id=agent_id,
                parent_id=existing_agent.get("parent_id"),
                sibling_group=existing_agent.get("sibling_group"),
                depth=child_depth,
                role=str(existing_agent.get("role") or "agent"),
                session_name=str(existing_agent.get("session_name") or frame.agent_handle or agent_id),
                cwd=frame.spec.cwd,
                agent_handle=frame.agent_handle,
                agent_type=frame.agent_type,
                run_kind=frame.run_kind,
                model=frame.model or "default",
            )
    except DuplicateAgentHandleError:
        return DispatchRejection(reason="duplicate_agent_handle")
    try:
        await asyncio.to_thread(
            store.create_run,
            run_id=frame.run_id,
            agent_id=agent_id,
            dispatcher_id=dispatcher_node_id,
            spec=spec_json,
            report_token_hash=report_token_hash,
        )
    except ActiveRunExistsError:
        return DispatchRejection(reason="active_run_exists")

    return PreparedDispatch(agent_id=agent_id, report_token=report_token, child_depth=child_depth)


async def _mark_spawn_failed(*, run_id: str, registry: Registry, store: Store) -> None:
    finalized = await asyncio.to_thread(
        store.set_run_result_if_unset,
        run_id=run_id,
        status="failed",
        result=None,
        error="spawn_failed",
    )
    if finalized:
        await notify_run_finalized(run_id, registry=registry, store=store)


async def dispatch_agent(
    *,
    frame: DispatchFrame,
    dispatcher_node_id: str,
    daemon_socket_path: str,
    registry: Registry,
    store: Store,
    reapers: set[asyncio.Task[None]],
) -> DispatchAck:
    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id=dispatcher_node_id,
        store=store,
    )
    if isinstance(dispatch, DispatchRejection):
        return DispatchAck(status="rejected", reason=dispatch.reason)

    try:
        process = await spawn_agent_process(
            run_id=frame.run_id,
            spec=frame.spec,
            agent_id=dispatch.agent_id,
            report_token=dispatch.report_token,
            daemon_socket_path=daemon_socket_path,
            dispatcher_node_id=dispatcher_node_id,
            child_depth=dispatch.child_depth,
        )
    except (FileNotFoundError, PermissionError, OSError, ValueError):
        await _mark_spawn_failed(run_id=frame.run_id, registry=registry, store=store)
        return DispatchAck(status="rejected", reason="spawn_failed")

    registry.set_run_owner(frame.run_id, dispatcher_node_id)
    registry.set_process(frame.run_id, process)

    async def on_finalize(run_id: str) -> None:
        await notify_run_finalized(run_id, registry=registry, store=store)

    reap_task = asyncio.create_task(
        reap_agent_process(
            run_id=frame.run_id,
            process=process,
            registry=registry,
            store=store,
            on_finalize=on_finalize,
        )
    )
    reapers.add(reap_task)
    reap_task.add_done_callback(reapers.discard)

    return DispatchAck(status="spawned", reason=None)


def _is_report_frame_authorized(*, frame: TelemetryFrame | ResultReportFrame, run: dict[str, Any] | None) -> bool:
    if not run:
        return False
    if frame.agent_id != run.get("agent_id"):
        return False
    report_token_hash = run.get("report_token_hash")
    if not isinstance(report_token_hash, str):
        return False
    return hmac.compare_digest(_hash_report_token(frame.report_token), report_token_hash)


async def handle_telemetry(*, frame: TelemetryFrame, store: Store) -> None:
    run = await asyncio.to_thread(store.get_run, frame.run_id)
    if not _is_report_frame_authorized(frame=frame, run=run):
        return
    await asyncio.to_thread(
        store.append_run_event,
        run_id=frame.run_id,
        kind=frame.kind,
        payload=frame.payload,
    )


async def handle_result_report(
    *,
    frame: ResultReportFrame,
    store: Store,
    registry: Registry,
) -> None:
    run = await asyncio.to_thread(store.get_run, frame.run_id)
    if not _is_report_frame_authorized(frame=frame, run=run):
        return
    run_status = "completed" if frame.status == "ok" else "failed"
    finalized = await asyncio.to_thread(
        store.set_run_result_if_unset,
        run_id=frame.run_id,
        status=run_status,
        result=frame.result,
        error=frame.error,
    )
    if finalized:
        await notify_run_finalized(frame.run_id, registry=registry, store=store)


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


async def list_agents(
    *,
    frame: ListAgentsFrame,
    store: Store,
    requester_node_id: str,
) -> list[ListAgentItem]:
    rows = await asyncio.to_thread(
        store.get_root_agent_directory,
        requester_node_id=requester_node_id,
        awaitable=frame.awaitable,
    )
    items: list[ListAgentItem] = []
    for row in rows:
        values: dict[str, Any] = {
            "agent_id": row["agent_id"],
            "agent_handle": row["agent_handle"],
            "parent_id": row["parent_id"],
            "role": row["role"],
            "session_name": row["session_name"],
            "depth": row["depth"],
            "status": row["status"],
            "awaitable": row["awaitable"],
        }
        if row.get("agent_type") is not None:
            values["agent_type"] = row["agent_type"]
        if row.get("run_kind") is not None:
            values["run_kind"] = row["run_kind"]
        items.append(ListAgentItem(**values))
    return items
