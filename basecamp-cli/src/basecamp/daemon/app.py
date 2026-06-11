"""FastAPI application for the basecamp daemon skeleton."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from basecamp.daemon.frames import (
    PROTOCOL_VERSION,
    DispatchAckFrame,
    DispatchFrame,
    ErrorFrame,
    RegisteredFrame,
    RegisterFrame,
    ResultReportFrame,
    TelemetryFrame,
    WaitFrame,
    WaitResultFrame,
    WaitResultItem,
    parse_frame,
    serialize_frame,
)
from basecamp.daemon.registry import Registry, Waiter
from basecamp.daemon.store import Store

_REDACTED_ENV_VALUE = "<redacted>"

DEFAULT_AGENT_MAX_DEPTH = 2
TERMINAL_RUN_STATUSES = {"completed", "failed"}


def create_app(store: Store, *, daemon_uds: str | None = None) -> FastAPI:
    """Create and configure the daemon FastAPI app."""

    app = FastAPI()
    registry = Registry()
    daemon_socket_path = daemon_uds or ""
    reapers: set[asyncio.Task[None]] = set()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "protocol": PROTOCOL_VERSION}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()

        node_id: str | None = None
        try:
            first_payload = await websocket.receive_json()
            if not isinstance(first_payload, dict):
                await _send_error_and_close(
                    websocket,
                    code="invalid_frame",
                    message="Expected a JSON object frame.",
                )
                return

            version = first_payload.get("v")
            if version != PROTOCOL_VERSION:
                await _send_error_and_close(
                    websocket,
                    code="protocol_version",
                    message=(f"Unsupported protocol version {version!r}; expected {PROTOCOL_VERSION}."),
                )
                return

            parsed = parse_frame(first_payload)
            if not isinstance(parsed, RegisterFrame):
                await _send_error_and_close(
                    websocket,
                    code="invalid_register",
                    message="First frame must be a register frame.",
                )
                return

            await asyncio.to_thread(
                store.upsert_agent,
                agent_id=parsed.node_id,
                parent_id=parsed.parent_id,
                sibling_group=parsed.sibling_group,
                depth=parsed.depth,
                role=parsed.role,
                session_name=parsed.session_name,
                cwd=parsed.cwd,
            )
            node_id = parsed.node_id
            registry.set_connection(parsed.node_id, websocket)

            registered = RegisteredFrame(
                type="registered",
                v=PROTOCOL_VERSION,
                node_id=parsed.node_id,
                protocol=PROTOCOL_VERSION,
            )
            await websocket.send_json(serialize_frame(registered))

            while True:
                payload = await websocket.receive_json()
                if not isinstance(payload, dict):
                    await _send_error_and_close(
                        websocket,
                        code="invalid_frame",
                        message="Expected a JSON object frame.",
                    )
                    return

                if payload.get("v") != PROTOCOL_VERSION:
                    await _send_error_and_close(
                        websocket,
                        code="protocol_version",
                        message=(f"Unsupported protocol version {payload.get('v')!r}; expected {PROTOCOL_VERSION}."),
                    )
                    return

                inbound = parse_frame(payload)
                if isinstance(inbound, DispatchFrame):
                    await _handle_dispatch(
                        websocket=websocket,
                        frame=inbound,
                        dispatcher_node_id=parsed.node_id,
                        daemon_socket_path=daemon_socket_path,
                        registry=registry,
                        store=store,
                        reapers=reapers,
                    )
                    continue
                if isinstance(inbound, TelemetryFrame):
                    await _handle_telemetry(frame=inbound, connection_node_id=parsed.node_id, store=store)
                    continue
                if isinstance(inbound, ResultReportFrame):
                    await _handle_result_report(
                        frame=inbound,
                        connection_node_id=parsed.node_id,
                        store=store,
                        registry=registry,
                    )
                    continue
                if isinstance(inbound, WaitFrame):
                    await _handle_wait(frame=inbound, websocket=websocket, store=store, registry=registry)
                    continue

        except WebSocketDisconnect:
            return
        except Exception as exc:  # noqa: BLE001
            await _send_error_and_close(
                websocket,
                code="invalid_frame",
                message=f"Failed to parse frame: {exc}",
            )
        finally:
            # Only drop the mapping if it still points at THIS socket; a reconnect
            # under the same node_id may have already installed a newer connection.
            if node_id is not None and registry.get_connection(node_id) is websocket:
                registry.remove_connection(node_id)

    return app


def _sanitize_dispatch_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Return a persisted copy of a dispatch spec with secrets removed.

    Keep env names for observability while dropping raw values to avoid persistence
    of credentials in SQLite.
    """

    env = spec.get("env")
    if isinstance(env, dict):
        env_keys = [str(key) for key in env.keys()]
        spec = dict(spec)
        spec["env"] = dict.fromkeys(env_keys, _REDACTED_ENV_VALUE)
        spec["env_keys"] = env_keys
    return spec


def _resolve_agent_max_depth() -> int:
    raw = os.getenv("BASECAMP_AGENT_MAX_DEPTH")
    try:
        value = int(raw) if raw is not None else DEFAULT_AGENT_MAX_DEPTH
    except ValueError:
        return DEFAULT_AGENT_MAX_DEPTH
    return value if value >= 0 else DEFAULT_AGENT_MAX_DEPTH


async def _handle_dispatch(
    *,
    websocket: WebSocket,
    frame: DispatchFrame,
    dispatcher_node_id: str,
    daemon_socket_path: str,
    registry: Registry,
    store: Store,
    reapers: set[asyncio.Task[None]],
) -> None:
    dispatcher = await asyncio.to_thread(store.get_agent, dispatcher_node_id)
    dispatcher_depth = int(dispatcher.get("depth", 0)) if dispatcher else 0
    child_depth = dispatcher_depth + 1
    max_depth = _resolve_agent_max_depth()
    if child_depth > max_depth:
        await websocket.send_json(
            serialize_frame(
                DispatchAckFrame(
                    type="dispatch_ack",
                    v=PROTOCOL_VERSION,
                    run_id=frame.run_id,
                    status="rejected",
                    reason="depth_cap",
                )
            )
        )
        return

    agent_id = frame.agent_id or str(uuid.uuid4())
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
    await asyncio.to_thread(
        store.create_run,
        run_id=frame.run_id,
        agent_id=agent_id,
        spec=spec_json,
    )

    argv = [*frame.spec.argv, frame.spec.task]
    child_env = {
        **frame.spec.env,
        "BASECAMP_DAEMON_UDS": daemon_socket_path,
        "BASECAMP_RUN_ID": frame.run_id,
        "BASECAMP_AGENT_ID": agent_id,
        "BASECAMP_PARENT_SESSION": dispatcher_node_id,
        "BASECAMP_AGENT_DEPTH": str(child_depth),
    }

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=frame.spec.cwd,
            env=child_env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except (FileNotFoundError, PermissionError, OSError, ValueError):
        finalized = await asyncio.to_thread(
            store.set_run_result_if_unset,
            run_id=frame.run_id,
            status="failed",
            result=None,
            error="spawn_failed",
        )
        if finalized:
            await _notify_run_finalized(frame.run_id, registry=registry, store=store)
        await websocket.send_json(
            serialize_frame(
                DispatchAckFrame(
                    type="dispatch_ack",
                    v=PROTOCOL_VERSION,
                    run_id=frame.run_id,
                    status="rejected",
                    reason="spawn_failed",
                )
            )
        )
        return

    registry.set_run_owner(frame.run_id, dispatcher_node_id)
    registry.set_process(frame.run_id, process)

    reap_task = asyncio.create_task(_reap_process(frame.run_id, process, registry, store))
    reapers.add(reap_task)
    reap_task.add_done_callback(reapers.discard)

    await websocket.send_json(
        serialize_frame(
            DispatchAckFrame(
                type="dispatch_ack",
                v=PROTOCOL_VERSION,
                run_id=frame.run_id,
                status="spawned",
                reason=None,
            )
        )
    )


async def _reap_process(run_id: str, process: asyncio.subprocess.Process, registry: Registry, store: Store) -> None:
    exit_code = await process.wait()
    await asyncio.to_thread(store.set_run_exit_code, run_id=run_id, exit_code=exit_code)

    finalized = await asyncio.to_thread(
        store.set_run_result_if_unset,
        run_id=run_id,
        status="failed",
        result=None,
        error=f"agent process exited (code {exit_code}) without reporting a result",
    )
    if finalized:
        await _notify_run_finalized(run_id, registry=registry, store=store)

    registry.pop_process(run_id)


async def _handle_telemetry(*, frame: TelemetryFrame, connection_node_id: str, store: Store) -> None:
    if frame.agent_id != connection_node_id:
        return
    await asyncio.to_thread(
        store.append_run_event,
        run_id=frame.run_id,
        kind=frame.kind,
        payload=frame.payload,
    )


async def _handle_result_report(
    *,
    frame: ResultReportFrame,
    connection_node_id: str,
    store: Store,
    registry: Registry,
) -> None:
    if frame.agent_id != connection_node_id:
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
        await _notify_run_finalized(frame.run_id, registry=registry, store=store)


async def _is_run_terminal(run_id: str, store: Store) -> bool:
    run = await asyncio.to_thread(store.get_run, run_id)
    if not run:
        return False
    status = run.get("status")
    return isinstance(status, str) and status in TERMINAL_RUN_STATUSES


async def _build_wait_results(
    *,
    run_ids: list[str],
    store: Store,
    terminal_only: bool,
) -> list[WaitResultItem]:
    rows = await asyncio.to_thread(store.get_run_wait_results, run_ids, terminal_only=terminal_only)
    by_id = {row["run_id"]: row for row in rows}
    ordered: list[WaitResultItem] = []
    for run_id in run_ids:
        row = by_id.get(run_id)
        if not row:
            continue
        status = row.get("status")
        if not isinstance(status, str) or status not in TERMINAL_RUN_STATUSES:
            continue
        ordered.append(
            WaitResultItem(
                run_id=run_id,
                status=status,
                result=row.get("result"),
                error=row.get("error"),
            )
        )
    return ordered


async def _notify_run_finalized(run_id: str, *, registry: Registry, store: Store) -> None:
    for waiter in registry.list_waiters():
        if waiter.future.done() or run_id not in waiter.run_ids:
            continue
        all_terminal = True
        for waiter_run_id in waiter.run_ids:
            if not await _is_run_terminal(waiter_run_id, store):
                all_terminal = False
                break
        # Re-check done(): an await happened above, so a concurrent finalize or the
        # wait_for timeout may have already resolved/cancelled this future.
        if all_terminal and not waiter.future.done():
            waiter.future.set_result(None)


async def _handle_wait(*, frame: WaitFrame, websocket: WebSocket, store: Store, registry: Registry) -> None:
    run_ids = list(dict.fromkeys(frame.run_ids))
    all_terminal = await asyncio.to_thread(store.are_runs_terminal, run_ids)
    if all_terminal:
        results = await _build_wait_results(run_ids=run_ids, store=store, terminal_only=False)
        await websocket.send_json(
            serialize_frame(WaitResultFrame(type="wait_result", v=PROTOCOL_VERSION, results=results))
        )
        return

    waiter = Waiter(
        waiter_id=str(uuid.uuid4()),
        websocket=websocket,
        run_ids=set(run_ids),
        future=asyncio.get_running_loop().create_future(),
    )
    registry.add_waiter(waiter)
    try:
        await asyncio.wait_for(waiter.future, timeout=frame.timeout_s)
        results = await _build_wait_results(run_ids=run_ids, store=store, terminal_only=False)
    except TimeoutError:
        results = await _build_wait_results(run_ids=run_ids, store=store, terminal_only=True)
    finally:
        registry.remove_waiter(waiter.waiter_id)

    await websocket.send_json(serialize_frame(WaitResultFrame(type="wait_result", v=PROTOCOL_VERSION, results=results)))


async def _send_error_and_close(websocket: WebSocket, *, code: str, message: str) -> None:
    error = ErrorFrame(type="error", v=PROTOCOL_VERSION, code=code, message=message)
    await websocket.send_json(serialize_frame(error))
    await websocket.close(code=1002)
