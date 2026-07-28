"""FastAPI application for the basecamp hub daemon."""

from __future__ import annotations

import asyncio
import sqlite3

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .dashboard.access import DashboardAccess
from .frames import (
    PROTOCOL_VERSION,
    AttachWorkstreamAgentFrame,
    CancelFrame,
    CreateWorkstreamFrame,
    DispatchFrame,
    ErrorFrame,
    ListAgentsFrame,
    MessageStatusFrame,
    PeerMessageDeliveryAckFrame,
    PeerMessageFrame,
    RegisteredFrame,
    RegisterFrame,
    ResultReportFrame,
    ReviseWorkstreamFrame,
    SessionMetadataFrame,
    TelemetryFrame,
    UpdateWorkstreamFrame,
    WaitFrame,
    parse_frame,
    serialize_frame,
)
from .handlers import (
    handle_attach_workstream_agent,
    handle_cancel,
    handle_create_workstream,
    handle_dispatch,
    handle_list_agents,
    handle_message_status,
    handle_peer_message,
    handle_revise_workstream,
    handle_update_workstream,
    handle_wait,
)
from .http_routes import register_http_routes
from .registry import Registry
from .store import DuplicateAgentHandleError, Store
from .swarm.service import (
    handle_peer_message_delivery_ack,
    handle_result_report,
    handle_telemetry,
    schedule_disconnect_reaper,
)

# Starlette's WebSocket cannot send a protocol-level ping; this is the timeout
# for the send-based incumbent probe (see _incumbent_is_live).
_INCUMBENT_PROBE_TIMEOUT_S = 10.0


def create_app(
    store: Store,
    *,
    daemon_uds: str | None = None,
    dashboard_access: DashboardAccess | None = None,
) -> FastAPI:
    """Create and configure the daemon FastAPI app."""

    app = FastAPI()
    registry = Registry()
    daemon_socket_path = daemon_uds or ""
    reapers: set[asyncio.Task[None]] = set()
    delivery_tasks: set[asyncio.Task[None]] = set()

    register_http_routes(app, store=store, registry=registry, dashboard_access=dashboard_access)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()

        node_id: str | None = None
        connection_generation = -1
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

            incumbent = registry.get_connection(parsed.node_id)
            if incumbent is not None:
                # Never blind-replace: a live incumbent keeps its session (an
                # accidental resume elsewhere gets a clean rejection); only a
                # provably unresponsive socket yields its node id.
                if await _incumbent_is_live(incumbent):
                    await _send_error_and_close(
                        websocket,
                        code="duplicate_node_connection",
                        message="Node is already connected.",
                    )
                    return
                await _close_websocket_quietly(incumbent)

            node_id = parsed.node_id
            connection_generation = registry.set_connection(parsed.node_id, websocket)
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
                    session_file=parsed.session_file,
                    repo=parsed.repo,
                    worktree_label=parsed.worktree_label,
                    branch=parsed.branch,
                    model=parsed.model,
                    agent_mode=parsed.agent_mode,
                )
            except DuplicateAgentHandleError as exc:
                registry.remove_connection(parsed.node_id, generation=connection_generation)
                await _send_error_and_close(
                    websocket,
                    code="duplicate_agent_handle",
                    message=str(exc),
                )
                return

            registered = RegisteredFrame(
                type="registered",
                node_id=parsed.node_id,
                protocol=PROTOCOL_VERSION,
            )
            await websocket.send_json(serialize_frame(registered))
            registry.cancel_disconnect_reaper(parsed.node_id)

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
                if isinstance(inbound, SessionMetadataFrame):
                    try:
                        await asyncio.to_thread(
                            store.update_agent_metadata,
                            agent_id=parsed.node_id,
                            session_name=inbound.session_name,
                            model=inbound.model,
                            agent_mode=inbound.agent_mode,
                            repo=inbound.repo,
                            worktree_label=inbound.worktree_label,
                            branch=inbound.branch,
                        )
                    except sqlite3.Error:
                        # Metadata is best effort; a persistence race must not end a healthy socket.
                        pass
                    continue
                if isinstance(inbound, DispatchFrame):
                    await handle_dispatch(
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
                    await handle_wait(
                        frame=inbound,
                        websocket=websocket,
                        store=store,
                        registry=registry,
                        requester_node_id=parsed.node_id,
                    )
                    continue
                if isinstance(inbound, ListAgentsFrame):
                    await handle_list_agents(
                        frame=inbound,
                        websocket=websocket,
                        store=store,
                        registry=registry,
                        requester_node_id=parsed.node_id,
                    )
                    continue
                if isinstance(inbound, PeerMessageFrame):
                    await handle_peer_message(
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
                    await handle_message_status(
                        frame=inbound,
                        websocket=websocket,
                        store=store,
                        registry=registry,
                        requester_node_id=parsed.node_id,
                    )
                    continue
                if isinstance(inbound, CancelFrame):
                    await handle_cancel(
                        frame=inbound,
                        websocket=websocket,
                        store=store,
                        registry=registry,
                        requester_node_id=parsed.node_id,
                    )
                    continue
                if isinstance(inbound, CreateWorkstreamFrame):
                    await handle_create_workstream(frame=inbound, websocket=websocket, store=store)
                    continue
                if isinstance(inbound, AttachWorkstreamAgentFrame):
                    await handle_attach_workstream_agent(
                        frame=inbound,
                        websocket=websocket,
                        store=store,
                        requester_node_id=parsed.node_id,
                    )
                    continue
                if isinstance(inbound, UpdateWorkstreamFrame):
                    await handle_update_workstream(frame=inbound, websocket=websocket, store=store)
                    continue
                if isinstance(inbound, ReviseWorkstreamFrame):
                    await handle_revise_workstream(frame=inbound, websocket=websocket, store=store)
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
            # Generation-guarded cleanup: a stale handler (replaced via takeover
            # of a zombie incumbent) must not remove or reap the newer entry.
            if node_id is not None and registry.remove_connection(node_id, generation=connection_generation):
                try:
                    await asyncio.to_thread(store.touch_agent, node_id)
                except sqlite3.Error:
                    # Reaping must still proceed when a best-effort recency write loses a shutdown race.
                    pass
                finally:
                    schedule_disconnect_reaper(node_id=node_id, registry=registry, store=store)

    return app


async def _incumbent_is_live(incumbent: WebSocket) -> bool:
    """Classify an incumbent connection: any outbound frame settles liveness.

    Starlette's WebSocket cannot send a protocol-level ping, so this uses the
    send path as the probe: a dead peer (half-open UDS after kill/sleep) fails
    the write, while a live one — including one merely busy in a long wait,
    whose buffer drains fine — accepts it. A failed classification must close
    the incumbent (via takeover), so the payload must be valid yet inert on
    every receiver: v28 ping frames are answered (harmless); pre-v28 peers
    error-close on the unknown type — which a failed probe was going to do
    anyway.
    """

    probe = {"type": "ping", "v": PROTOCOL_VERSION, "nonce": ""}
    try:
        async with asyncio.timeout(_INCUMBENT_PROBE_TIMEOUT_S):
            await incumbent.send_json(probe)
    except Exception:  # noqa: BLE001 — any send failure reads as a dead incumbent
        return False
    return True


async def _close_websocket_quietly(websocket: WebSocket) -> None:
    try:
        async with asyncio.timeout(2.0):
            await websocket.close(code=1000)
    except Exception:  # noqa: BLE001 — close is best effort; takeover proceeds
        return


async def _send_error_and_close(websocket: WebSocket, *, code: str, message: str) -> None:
    error = ErrorFrame(type="error", code=code, message=message)
    await websocket.send_json(serialize_frame(error))
    await websocket.close(code=1002)
