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
    parse_frame,
    serialize_frame,
)
from basecamp.daemon.registry import Registry
from basecamp.daemon.store import Store

DEFAULT_AGENT_MAX_DEPTH = 2


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
                    await _handle_result_report(frame=inbound, connection_node_id=parsed.node_id, store=store)
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
            if node_id is not None:
                registry.remove_connection(node_id)

    return app


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

    agent_id = str(uuid.uuid4())
    spec_json = frame.spec.model_dump(mode="json")
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
        await asyncio.to_thread(
            store.set_run_result,
            run_id=frame.run_id,
            status="failed",
            result=None,
            error="spawn_failed",
        )
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


async def _handle_result_report(*, frame: ResultReportFrame, connection_node_id: str, store: Store) -> None:
    if frame.agent_id != connection_node_id:
        return
    run_status = "completed" if frame.status == "ok" else "failed"
    await asyncio.to_thread(
        store.set_run_result,
        run_id=frame.run_id,
        status=run_status,
        result=frame.result,
        error=frame.error,
    )


async def _send_error_and_close(websocket: WebSocket, *, code: str, message: str) -> None:
    error = ErrorFrame(type="error", v=PROTOCOL_VERSION, code=code, message=message)
    await websocket.send_json(serialize_frame(error))
    await websocket.close(code=1002)
