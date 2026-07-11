"""Dispatch orchestration: validate and persist dispatches, spawn agent runs."""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ...frames import DispatchFrame
from ...registry import Registry
from ...store import ActiveRunExistsError, DuplicateAgentHandleError, Store
from ..process import reap_agent_process, spawn_agent_process
from ..run_result import agent_session_file
from .messaging import _public_message_handle
from .waiting import notify_run_finalized

_REDACTED_ENV_VALUE = "<redacted>"

DEFAULT_AGENT_MAX_DEPTH = 2

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
