"""FastAPI application for the pi-swarm daemon."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .frames import (
    PROTOCOL_VERSION,
    DispatchAckFrame,
    DispatchFrame,
    ErrorFrame,
    ListAgentsFrame,
    ListAgentsResultFrame,
    MessageStatusFrame,
    PeerMessageDeliveryAckFrame,
    PeerMessageDeliveryFrame,
    PeerMessageFrame,
    RegisteredFrame,
    RegisterFrame,
    ResultReportFrame,
    TelemetryFrame,
    WaitFrame,
    WaitResultFrame,
    parse_frame,
    serialize_frame,
)
from .registry import Registry
from .service import (
    AcceptedPeerMessage,
    accept_peer_message,
    dispatch_agent,
    handle_peer_message_delivery_ack,
    handle_result_report,
    handle_telemetry,
    list_agents,
    message_status_result,
    notify_message_delivery_terminal,
    wait_for_agents,
)
from .store import DuplicateAgentHandleError, Store


def create_app(store: Store, *, daemon_uds: str | None = None) -> FastAPI:
    """Create and configure the daemon FastAPI app."""

    app = FastAPI()
    registry = Registry()
    daemon_socket_path = daemon_uds or ""
    reapers: set[asyncio.Task[None]] = set()
    delivery_tasks: set[asyncio.Task[None]] = set()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "protocol": PROTOCOL_VERSION}

    @app.get("/runs/summary")
    async def runs_summary(root_id: str, limit: int = 5) -> dict[str, Any]:
        summary = await asyncio.to_thread(
            store.get_run_summary,
            root_id,
            limit=limit,
        )
        summary["session_active"] = registry.has_connection(root_id)
        return summary

    @app.get("/runs/messages")
    async def runs_messages(root_id: str, agent_handle: str, limit: int = 3) -> dict[str, Any]:
        return await asyncio.to_thread(
            store.get_run_messages,
            root_id,
            agent_handle=agent_handle,
            limit=limit,
        )

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

            if registry.has_connection(parsed.node_id):
                await _send_error_and_close(
                    websocket,
                    code="duplicate_node_connection",
                    message="Node is already connected.",
                )
                return

            node_id = parsed.node_id
            registry.set_connection(parsed.node_id, websocket)
            try:
                await asyncio.to_thread(
                    store.upsert_agent,
                    agent_id=parsed.node_id,
                    parent_id=parsed.parent_id,
                    sibling_group=parsed.sibling_group,
                    depth=parsed.depth,
                    role=parsed.role,
                    session_name=parsed.session_name,
                    cwd=parsed.cwd,
                    agent_handle=parsed.agent_handle,
                )
            except DuplicateAgentHandleError as exc:
                if registry.get_connection(parsed.node_id) is websocket:
                    registry.remove_connection(parsed.node_id)
                await _send_error_and_close(
                    websocket,
                    code="duplicate_agent_handle",
                    message=str(exc),
                )
                return

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
                    await handle_telemetry(frame=inbound, store=store)
                    continue
                if isinstance(inbound, ResultReportFrame):
                    await handle_result_report(
                        frame=inbound,
                        store=store,
                        registry=registry,
                    )
                    continue
                if isinstance(inbound, WaitFrame):
                    await _handle_wait(
                        frame=inbound,
                        websocket=websocket,
                        store=store,
                        registry=registry,
                        requester_node_id=parsed.node_id,
                    )
                    continue
                if isinstance(inbound, ListAgentsFrame):
                    await _handle_list_agents(
                        frame=inbound,
                        websocket=websocket,
                        store=store,
                        requester_node_id=parsed.node_id,
                    )
                    continue
                if isinstance(inbound, PeerMessageFrame):
                    await _handle_peer_message(
                        frame=inbound,
                        websocket=websocket,
                        store=store,
                        registry=registry,
                        requester_node_id=parsed.node_id,
                        delivery_tasks=delivery_tasks,
                    )
                    continue
                if isinstance(inbound, PeerMessageDeliveryAckFrame):
                    await handle_peer_message_delivery_ack(
                        frame=inbound,
                        acking_node_id=parsed.node_id,
                        store=store,
                        registry=registry,
                    )
                    continue
                if isinstance(inbound, MessageStatusFrame):
                    await websocket.send_json(
                        serialize_frame(
                            await message_status_result(
                                frame=inbound,
                                requester_node_id=parsed.node_id,
                                store=store,
                                registry=registry,
                            )
                        )
                    )
                    continue

                await _send_error_and_close(
                    websocket,
                    code="unsupported_frame",
                    message=f"Unsupported inbound frame type {inbound.type!r}.",
                )
                return

        except WebSocketDisconnect:
            return
        except Exception as exc:  # noqa: BLE001
            await _send_error_and_close(
                websocket,
                code="invalid_frame",
                message=f"Failed to parse frame: {exc}",
            )
        finally:
            if node_id is not None and registry.get_connection(node_id) is websocket:
                registry.remove_connection(node_id)

    return app


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
    ack = await dispatch_agent(
        frame=frame,
        dispatcher_node_id=dispatcher_node_id,
        daemon_socket_path=daemon_socket_path,
        registry=registry,
        store=store,
        reapers=reapers,
    )
    await _send_dispatch_ack(websocket, run_id=frame.run_id, status=ack.status, reason=ack.reason)


async def _handle_wait(
    *,
    frame: WaitFrame,
    websocket: WebSocket,
    store: Store,
    registry: Registry,
    requester_node_id: str,
) -> None:
    results = await wait_for_agents(
        frame=frame,
        store=store,
        registry=registry,
        requester_node_id=requester_node_id,
    )
    await websocket.send_json(serialize_frame(WaitResultFrame(type="wait_result", v=PROTOCOL_VERSION, results=results)))


async def _handle_list_agents(
    *,
    frame: ListAgentsFrame,
    websocket: WebSocket,
    store: Store,
    requester_node_id: str,
) -> None:
    result = ListAgentsResultFrame(
        type="list_agents_result",
        v=PROTOCOL_VERSION,
        request_id=frame.request_id,
        agents=await list_agents(frame=frame, store=store, requester_node_id=requester_node_id),
    )
    await websocket.send_json(serialize_frame(result))


async def _handle_peer_message(
    *,
    frame: PeerMessageFrame,
    websocket: WebSocket,
    store: Store,
    registry: Registry,
    requester_node_id: str,
    delivery_tasks: set[asyncio.Task[None]],
) -> None:
    accepted = await accept_peer_message(frame=frame, requester_node_id=requester_node_id, store=store)
    if not isinstance(accepted, AcceptedPeerMessage):
        await websocket.send_json(serialize_frame(accepted))
        return

    task = asyncio.create_task(
        _push_peer_message_delivery(
            delivery=accepted.delivery,
            target_agent_id=accepted.target_agent_id,
            registry=registry,
            store=store,
        )
    )
    delivery_tasks.add(task)
    task.add_done_callback(delivery_tasks.discard)
    await websocket.send_json(serialize_frame(accepted.ack))


async def _push_peer_message_delivery(
    *,
    delivery: PeerMessageDeliveryFrame,
    target_agent_id: str,
    registry: Registry,
    store: Store,
) -> None:
    target_websocket = registry.get_connection(target_agent_id)
    if target_websocket is None:
        updated = await asyncio.to_thread(
            store.mark_message_unavailable,
            delivery.message_id,
            "target_unavailable",
        )
        if updated:
            notify_message_delivery_terminal(delivery.message_id, registry=registry)
        return

    try:
        await target_websocket.send_json(serialize_frame(delivery))
    except Exception as exc:  # noqa: BLE001
        updated = await asyncio.to_thread(store.mark_message_failed, delivery.message_id, str(exc))
        if updated:
            notify_message_delivery_terminal(delivery.message_id, registry=registry)
        return

    await asyncio.to_thread(store.mark_message_sent, delivery.message_id)


async def _send_dispatch_ack(
    websocket: WebSocket,
    *,
    run_id: str,
    status: Literal["spawned", "rejected"],
    reason: str | None,
) -> None:
    await websocket.send_json(
        serialize_frame(
            DispatchAckFrame(
                type="dispatch_ack",
                v=PROTOCOL_VERSION,
                run_id=run_id,
                status=status,
                reason=reason,
            )
        )
    )


async def _send_error_and_close(websocket: WebSocket, *, code: str, message: str) -> None:
    error = ErrorFrame(type="error", v=PROTOCOL_VERSION, code=code, message=message)
    await websocket.send_json(serialize_frame(error))
    await websocket.close(code=1002)
