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
from .store import ActiveRunExistsError, Store

_REDACTED_ENV_VALUE = "<redacted>"

DEFAULT_AGENT_MAX_DEPTH = 2
TERMINAL_RUN_STATUSES = {"completed", "failed"}

DispatchAckStatus = Literal["spawned", "rejected"]
DispatchAckReason = Literal["depth_cap", "active_run_exists", "spawn_failed"]
DispatchRejectionReason = Literal["depth_cap", "active_run_exists"]


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
    child_depth = dispatcher_depth + 1
    max_depth = _resolve_agent_max_depth()
    if child_depth > max_depth:
        return DispatchRejection(reason="depth_cap")

    agent_id = frame.agent_id or str(uuid.uuid4())
    report_token = _generate_report_token()
    report_token_hash = _hash_report_token(report_token)
    spec_json = _sanitize_dispatch_spec(frame.spec.model_dump(mode="json"))
    await asyncio.to_thread(
        store.upsert_agent,
        agent_id=agent_id,
        parent_id=dispatcher_node_id,
        sibling_group=None,
        depth=child_depth,
        role="agent",
        session_name=agent_id,
        cwd=frame.spec.cwd,
    )
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


def _row_unknown_result(agent_id: str) -> WaitResultItem:
    return WaitResultItem(agent_id=agent_id, status="unknown", result=None, error=None)


def build_wait_results(
    *,
    agent_ids: list[str],
    rows: list[dict[str, Any]],
) -> list[WaitResultItem]:
    by_id = {row["agent_id"]: row for row in rows if isinstance(row.get("agent_id"), str)}
    ordered: list[WaitResultItem] = []

    for agent_id in agent_ids:
        row = by_id.get(agent_id)
        if row is None:
            ordered.append(_row_unknown_result(agent_id))
            continue

        status = row.get("status")
        if not isinstance(status, str):
            ordered.append(_row_unknown_result(agent_id))
            continue

        wait_status = _normalize_wait_status(status)
        if wait_status in TERMINAL_RUN_STATUSES:
            ordered.append(
                WaitResultItem(
                    agent_id=agent_id,
                    status=wait_status,
                    result=row.get("result"),
                    error=row.get("error"),
                )
            )
            continue

        ordered.append(
            WaitResultItem(
                agent_id=agent_id,
                status="running",
                result=None,
                error=None,
            )
        )

    return ordered


async def build_wait_projection(
    *,
    agent_ids: list[str],
    store: Store,
    requester_node_id: str,
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(
        store.get_agents_current_runs,
        agent_ids,
        dispatcher_id=requester_node_id,
    )


def wait_target_run_ids(
    *,
    rows: list[dict[str, Any]],
    agent_ids: list[str],
) -> set[str]:
    by_agent_id = {row["agent_id"]: row for row in rows if isinstance(row.get("agent_id"), str)}
    targets: set[str] = set()
    for agent_id in agent_ids:
        row = by_agent_id.get(agent_id)
        if row is None:
            continue
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
    rows = await build_wait_projection(
        agent_ids=agent_ids,
        store=store,
        requester_node_id=requester_node_id,
    )
    run_ids_to_wait = wait_target_run_ids(rows=rows, agent_ids=agent_ids)

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

    return build_wait_results(
        agent_ids=agent_ids,
        rows=await build_wait_projection(
            agent_ids=agent_ids,
            store=store,
            requester_node_id=requester_node_id,
        ),
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
    return [
        ListAgentItem(
            agent_id=row["agent_id"],
            parent_id=row["parent_id"],
            role=row["role"],
            session_name=row["session_name"],
            depth=row["depth"],
            status=row["status"],
            awaitable=row["awaitable"],
        )
        for row in rows
    ]
