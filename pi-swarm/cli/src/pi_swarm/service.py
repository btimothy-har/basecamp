"""Daemon orchestration services independent of HTTP/WebSocket transport."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import os
import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .frames import (
    PROTOCOL_VERSION,
    DispatchFrame,
    ListAgentItem,
    ListAgentsFrame,
    MessageStatusFrame,
    MessageStatusResultFrame,
    PeerMessageAckFrame,
    PeerMessageDeliveryAckFrame,
    PeerMessageDeliveryFrame,
    PeerMessageFrame,
    ResultReportFrame,
    TelemetryFrame,
    WaitFrame,
    WaitResultItem,
)
from .process import reap_agent_process, spawn_agent_process, terminate_process_group
from .registry import MessageWaiter, Registry, Waiter
from .run_result import agent_session_file
from .store import (
    ActiveRunExistsError,
    DuplicateAgentHandleError,
    Store,
    _safe_product_role,
    is_message_delivery_terminal,
)

_REDACTED_ENV_VALUE = "<redacted>"

DEFAULT_AGENT_MAX_DEPTH = 2
DEFAULT_DISCONNECT_GRACE_SECONDS = 3600.0
DEFAULT_MESSAGE_WAIT_TIMEOUT_SECONDS = 30.0
MAX_MESSAGE_WAIT_TIMEOUT_SECONDS = 300.0
TERMINAL_RUN_STATUSES = {"completed", "failed"}

DispatchAckStatus = Literal["spawned", "rejected"]
DispatchAckReason = Literal[
    "depth_cap",
    "active_run_exists",
    "duplicate_agent_handle",
    "agent_type_mismatch",
    "fork_target_unknown",
    "not_dispatchable",
    "spawn_failed",
]
DispatchRejectionReason = Literal[
    "depth_cap",
    "active_run_exists",
    "duplicate_agent_handle",
    "agent_type_mismatch",
    "fork_target_unknown",
    "not_dispatchable",
]


@dataclass(frozen=True)
class DispatchAck:
    status: DispatchAckStatus
    reason: DispatchAckReason | None


@dataclass(frozen=True)
class AcceptedPeerMessage:
    ack: PeerMessageAckFrame
    delivery: PeerMessageDeliveryFrame
    target_agent_id: str


@dataclass(frozen=True)
class PreparedDispatch:
    agent_id: str
    report_token: str
    child_depth: int
    agent_handle: str | None = None
    fork_source_path: str | None = None


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


def _sender_product_role(sender: dict[str, Any] | None) -> str | None:
    if sender is None:
        return None
    if sender.get("role") == "agent":
        return _safe_product_role(sender.get("agent_type")) or "subagent"
    return _safe_product_role(sender.get("product_role")) or None


def _hash_report_token(report_token: str) -> str:
    return hashlib.sha256(report_token.encode("utf-8")).hexdigest()


def _metadata_mismatches(*, existing: dict[str, Any], frame: DispatchFrame) -> bool:
    existing_agent_type = existing.get("agent_type")
    if isinstance(existing_agent_type, str) and frame.agent_type and existing_agent_type != frame.agent_type:
        return True

    existing_run_kind = existing.get("run_kind")
    return bool(isinstance(existing_run_kind, str) and frame.run_kind and existing_run_kind != frame.run_kind)


def _is_dispatchable_agent(agent: dict[str, Any]) -> bool:
    return agent.get("role") != "session" and agent.get("agent_type") != "ask"


def _registered_session_file(agent: dict[str, Any]) -> Path | None:
    raw = agent.get("session_file")
    if not isinstance(raw, str) or not raw.strip():
        return None

    path = Path(raw).expanduser()
    if not path.is_absolute():
        return None
    try:
        path.lstat()
    except OSError:
        return None
    if path.is_symlink() or not path.is_file():
        return None
    return path.resolve()


def _resolve_fork_source_path(agent: dict[str, Any]) -> str | None:
    session_file = _registered_session_file(agent)
    if session_file is not None:
        return str(session_file)

    agent_id = agent.get("id")
    if not isinstance(agent_id, str):
        return None

    # Resolve daemon-spawned agent sidecars under the daemon's own home, never
    # requester-supplied env, so a fork source cannot be redirected.
    sidecar = agent_session_file(agent_id)
    return str(sidecar) if sidecar is not None else None


def _resolve_agent_max_depth() -> int:
    raw = os.getenv("BASECAMP_AGENT_MAX_DEPTH")
    try:
        value = int(raw) if raw is not None else DEFAULT_AGENT_MAX_DEPTH
    except ValueError:
        return DEFAULT_AGENT_MAX_DEPTH
    return value if value >= 0 else DEFAULT_AGENT_MAX_DEPTH


def _resolve_disconnect_grace_s() -> float:
    raw = os.getenv("BASECAMP_AGENT_DISCONNECT_GRACE_S")
    try:
        value = float(raw) if raw is not None else DEFAULT_DISCONNECT_GRACE_SECONDS
    except ValueError:
        return DEFAULT_DISCONNECT_GRACE_SECONDS
    return value if value >= 0 else DEFAULT_DISCONNECT_GRACE_SECONDS


async def _run_disconnect_reaper(
    *,
    node_id: str,
    registry: Registry,
    store: Store,
    grace_s: float,
) -> None:
    await asyncio.sleep(grace_s)
    if registry.has_connection(node_id):
        return

    for run_id in registry.live_run_ids_for_owner(node_id):
        finalized = await asyncio.to_thread(
            store.set_run_result_if_unset,
            run_id=run_id,
            status="failed",
            result=None,
            error="dispatcher_disconnected",
        )
        process = registry.get_process(run_id)
        if process is not None:
            await asyncio.to_thread(terminate_process_group, process.pid)
        if finalized:
            await notify_run_finalized(run_id, registry=registry, store=store)


def schedule_disconnect_reaper(
    *,
    node_id: str,
    registry: Registry,
    store: Store,
    grace_s: float | None = None,
) -> None:
    resolved_grace_s = _resolve_disconnect_grace_s() if grace_s is None else grace_s
    task = asyncio.create_task(
        _run_disconnect_reaper(
            node_id=node_id,
            registry=registry,
            store=store,
            grace_s=resolved_grace_s,
        )
    )
    registry.set_disconnect_reaper(node_id, task)
    task.add_done_callback(lambda done_task: registry.discard_disconnect_reaper(node_id, done_task))


async def prepare_dispatch(
    *,
    frame: DispatchFrame,
    dispatcher_node_id: str,
    store: Store,
) -> PreparedDispatch | DispatchRejection:
    dispatcher = await asyncio.to_thread(store.get_agent, dispatcher_node_id)
    dispatcher_depth = int(dispatcher.get("depth", 0)) if dispatcher else 0
    existing_by_handle = None
    if frame.agent_handle:
        existing_by_handle = await asyncio.to_thread(store.get_agent_by_handle, frame.agent_handle)
    existing_by_id = None
    if frame.agent_id:
        existing_by_id = await asyncio.to_thread(store.get_agent, frame.agent_id)

    if (
        existing_by_handle is not None
        and existing_by_id is not None
        and existing_by_handle.get("id") != existing_by_id.get("id")
    ):
        return DispatchRejection(reason="duplicate_agent_handle")

    existing_agent = existing_by_handle or existing_by_id
    resolved_handle = frame.agent_handle
    if existing_agent is not None:
        existing_agent_id = str(existing_agent.get("id"))
        requester_root = await asyncio.to_thread(store.resolve_agent_root, dispatcher_node_id)
        existing_agent_root = await asyncio.to_thread(store.resolve_agent_root, existing_agent_id)
        if requester_root is None or existing_agent_root != requester_root:
            return DispatchRejection(reason="duplicate_agent_handle")
        if frame.agent_id and frame.agent_id != existing_agent_id:
            return DispatchRejection(reason="duplicate_agent_handle")
        if not _is_dispatchable_agent(existing_agent):
            return DispatchRejection(reason="not_dispatchable")
        if _metadata_mismatches(existing=existing_agent, frame=frame):
            return DispatchRejection(reason="agent_type_mismatch")
        # A reused agent keeps its persisted canonical handle; a caller may not
        # rename it via a conflicting handle on retask.
        stored_handle = existing_agent.get("agent_handle")
        if isinstance(stored_handle, str) and stored_handle:
            if frame.agent_handle and frame.agent_handle != stored_handle:
                return DispatchRejection(reason="duplicate_agent_handle")
            resolved_handle = stored_handle
        agent_id = existing_agent_id
        child_depth = int(existing_agent.get("depth", dispatcher_depth + 1))
    else:
        agent_id = frame.agent_id or str(uuid.uuid4())
        child_depth = dispatcher_depth + 1

    max_depth = _resolve_agent_max_depth()
    if child_depth > max_depth:
        return DispatchRejection(reason="depth_cap")

    fork_source_path = None
    if frame.spec.fork_from:
        fork_target = await asyncio.to_thread(store.get_agent_by_handle, frame.spec.fork_from)
        # Only a match by public handle earns known-handle contact; the private-id
        # fallback below stays gated on relationship reachability.
        addressed_by_public_handle = (
            fork_target is not None and _public_message_handle(fork_target) == frame.spec.fork_from
        )
        if fork_target is None:
            fork_target = await asyncio.to_thread(store.get_agent, frame.spec.fork_from)
        if fork_target is None:
            return DispatchRejection(reason="fork_target_unknown")

        fork_target_id = fork_target.get("id")
        if not isinstance(fork_target_id, str):
            return DispatchRejection(reason="fork_target_unknown")
        if not await asyncio.to_thread(
            store.can_ask,
            dispatcher_node_id,
            fork_target_id,
            addressed_by_public_handle=addressed_by_public_handle,
        ):
            return DispatchRejection(reason="fork_target_unknown")

        fork_source_path = _resolve_fork_source_path(fork_target)
        if fork_source_path is None:
            return DispatchRejection(reason="fork_target_unknown")

    report_token = _generate_report_token()
    report_token_hash = _hash_report_token(report_token)
    spec_json = _sanitize_dispatch_spec(frame.spec.model_dump(mode="json"))
    try:
        if existing_agent is None:
            await asyncio.to_thread(
                store.upsert_agent,
                agent_id=agent_id,
                parent_id=dispatcher_node_id,
                sibling_group=dispatcher_node_id,
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
                session_name=str(existing_agent.get("session_name") or resolved_handle or agent_id),
                cwd=frame.spec.cwd,
                agent_handle=resolved_handle,
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

    return PreparedDispatch(
        agent_id=agent_id,
        report_token=report_token,
        child_depth=child_depth,
        agent_handle=resolved_handle,
        fork_source_path=fork_source_path,
    )


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
            agent_handle=dispatch.agent_handle,
            fork_source_path=dispatch.fork_source_path,
        )
    except (FileNotFoundError, PermissionError, OSError, ValueError):
        await _mark_spawn_failed(run_id=frame.run_id, registry=registry, store=store)
        return DispatchAck(status="rejected", reason="spawn_failed")

    registry.set_run_owner(frame.run_id, dispatcher_node_id)
    registry.set_process(frame.run_id, process)
    await asyncio.to_thread(store.set_run_pgid, run_id=frame.run_id, pgid=process.pid)

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


async def accept_peer_message(
    *,
    frame: PeerMessageFrame,
    requester_node_id: str,
    store: Store,
) -> AcceptedPeerMessage | PeerMessageAckFrame:
    """Authorize and persist a peer message before any delivery attempt."""

    target = await asyncio.to_thread(store.get_agent_by_handle, frame.target_handle)
    target_agent_id = target.get("id") if target is not None else None
    target_handle = _public_message_handle(target)
    if (
        not isinstance(target_agent_id, str)
        or not isinstance(target_handle, str)
        or target_handle != frame.target_handle
    ):
        return _unknown_peer_message_ack(frame.request_id)

    # The target was resolved and round-trip validated by its public handle above,
    # so this contact is authorized as known-handle addressing.
    if not await asyncio.to_thread(
        store.can_message,
        requester_node_id,
        target_agent_id,
        addressed_by_public_handle=True,
    ):
        return _unknown_peer_message_ack(frame.request_id)

    root_id = await asyncio.to_thread(store.resolve_agent_root, requester_node_id)
    if root_id is None:
        return _unknown_peer_message_ack(frame.request_id)

    sender = await asyncio.to_thread(store.get_agent, requester_node_id)
    sender_handle = _public_sender_handle(sender)
    sender_product_role = _sender_product_role(sender)
    sender_relation = await asyncio.to_thread(store.agent_relation, target_agent_id, requester_node_id)
    message_id = f"msg-{uuid.uuid4()}"
    await asyncio.to_thread(
        store.create_message,
        message_id=message_id,
        root_id=root_id,
        sender_node_id=requester_node_id,
        sender_handle=sender_handle,
        target_agent_id=target_agent_id,
        target_handle=target_handle,
        content=frame.message,
        interrupt=frame.interrupt,
    )

    delivery_values: dict[str, Any] = {
        "type": "peer_message_delivery",
        "v": PROTOCOL_VERSION,
        "message_id": message_id,
        "from_handle": sender_handle,
        "from_relation": sender_relation,
        "message": frame.message,
        "interrupt": frame.interrupt,
    }
    if sender_product_role is not None:
        delivery_values["from_product_role"] = sender_product_role

    return AcceptedPeerMessage(
        ack=PeerMessageAckFrame(
            type="peer_message_ack",
            v=PROTOCOL_VERSION,
            request_id=frame.request_id,
            message_id=message_id,
            status="accepted",
            error=None,
        ),
        delivery=PeerMessageDeliveryFrame(**delivery_values),
        target_agent_id=target_agent_id,
    )


async def handle_peer_message_delivery_ack(
    *,
    frame: PeerMessageDeliveryAckFrame,
    acking_node_id: str,
    store: Store,
    registry: Registry,
) -> None:
    """Apply a recipient delivery acknowledgement when authorized."""

    message = await asyncio.to_thread(store.get_message, frame.message_id)
    if message is None or message.get("target_agent_id") != acking_node_id:
        return

    if frame.status == "queued":
        updated = await asyncio.to_thread(store.mark_message_queued, frame.message_id)
    else:
        updated = await asyncio.to_thread(store.mark_message_failed, frame.message_id, frame.error)

    if updated:
        notify_message_delivery_terminal(frame.message_id, registry=registry)


async def message_status_result(
    *,
    frame: MessageStatusFrame,
    requester_node_id: str,
    store: Store,
    registry: Registry,
) -> MessageStatusResultFrame:
    """Return message status, optionally waiting for terminal delivery."""

    status = await asyncio.to_thread(store.get_message_status, requester_node_id, frame.message_id)
    if frame.wait_until_delivery and not is_message_delivery_terminal(str(status["status"])):
        waiter = MessageWaiter(
            waiter_id=str(uuid.uuid4()),
            message_id=frame.message_id,
            future=asyncio.get_running_loop().create_future(),
        )
        registry.add_message_waiter(waiter)
        try:
            status = await asyncio.to_thread(store.get_message_status, requester_node_id, frame.message_id)
            if not is_message_delivery_terminal(str(status["status"])):
                await asyncio.wait_for(waiter.future, timeout=_message_wait_timeout(frame.timeout_s))
        except TimeoutError:
            pass
        finally:
            registry.remove_message_waiter(waiter.waiter_id)
        status = await asyncio.to_thread(store.get_message_status, requester_node_id, frame.message_id)

    return MessageStatusResultFrame(
        type="message_status_result",
        v=PROTOCOL_VERSION,
        request_id=frame.request_id,
        **status,
    )


def notify_message_delivery_terminal(message_id: str, *, registry: Registry) -> None:
    """Wake in-memory waiters for a message that reached terminal delivery."""

    for waiter in registry.list_message_waiters():
        if waiter.message_id == message_id and not waiter.future.done():
            waiter.future.set_result(None)


def _unknown_peer_message_ack(request_id: str) -> PeerMessageAckFrame:
    return PeerMessageAckFrame(
        type="peer_message_ack",
        v=PROTOCOL_VERSION,
        request_id=request_id,
        message_id=None,
        status="unknown",
        error=None,
    )


def _public_sender_handle(sender: dict[str, Any] | None) -> str | None:
    return _public_message_handle(sender)


def _public_message_handle(agent: dict[str, Any] | None) -> str | None:
    if agent is None or agent.get("role") not in {"agent", "session"}:
        return None
    return _public_handle(agent)


def _public_agent_handle(agent: dict[str, Any] | None) -> str | None:
    if agent is None or agent.get("role") != "agent":
        return None
    return _public_handle(agent)


def _public_handle(agent: dict[str, Any]) -> str | None:
    handle = agent.get("agent_handle")
    agent_id = agent.get("id")
    if not isinstance(handle, str) or not handle:
        return None
    if isinstance(agent_id, str) and handle == agent_id:
        return None
    return handle


def _message_wait_timeout(timeout_s: float | None) -> float:
    if timeout_s is None:
        return DEFAULT_MESSAGE_WAIT_TIMEOUT_SECONDS
    if not math.isfinite(timeout_s):
        return MAX_MESSAGE_WAIT_TIMEOUT_SECONDS if timeout_s > 0 else 0.0
    return min(MAX_MESSAGE_WAIT_TIMEOUT_SECONDS, max(0.0, timeout_s))


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
        if row.get("task") is not None:
            values["task"] = row["task"]
        if row.get("agent_type") is not None:
            values["agent_type"] = row["agent_type"]
        if row.get("run_kind") is not None:
            values["run_kind"] = row["run_kind"]
        items.append(ListAgentItem(**values))
    return items
