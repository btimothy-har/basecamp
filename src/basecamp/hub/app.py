"""FastAPI application for the basecamp hub daemon."""

from __future__ import annotations

import asyncio
import sqlite3
from uuid import uuid4

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
    PingFrame,
    PongFrame,
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
_TAKEOVER_CLOSE_TIMEOUT_S = 2.0


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
    # Deliveries target other connections, so they outlive the requester's socket.
    delivery_tasks: set[asyncio.Task[None]] = set()

    register_http_routes(app, store=store, registry=registry, dashboard_access=dashboard_access)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()

        node_id: str | None = None
        connection_generation = -1
        # Waits reply to *this* socket, so they belong to this connection and are
        # cancelled when it goes away — otherwise a client that disconnects
        # mid-wait leaves a task awaiting a run only to write to a dead socket.
        reply_tasks: set[asyncio.Task[None]] = set()
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
            incumbent_generation = registry.get_connection_generation(parsed.node_id)
            if incumbent is not None:
                # Never blind-replace: a live incumbent keeps its session (an
                # accidental resume elsewhere gets a clean rejection); only a
                # peer that fails to answer its probe yields its node id.
                if await _incumbent_is_live(incumbent, parsed.node_id, registry):
                    await _send_error_and_close(
                        websocket,
                        code="duplicate_node_connection",
                        message="Node is already connected.",
                    )
                    return
                await _close_websocket_quietly(incumbent)

            # Probing suspends, so re-establish the claim atomically: another
            # registration for this node id may have settled while we waited.
            claimed = registry.claim_connection(parsed.node_id, websocket, replacing=incumbent_generation)
            if claimed is None:
                await _send_error_and_close(
                    websocket,
                    code="duplicate_node_connection",
                    message="Node is already connected.",
                )
                return

            node_id = parsed.node_id
            connection_generation = claimed
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
                if isinstance(inbound, PingFrame):
                    await websocket.send_json(serialize_frame(PongFrame(type="pong", nonce=inbound.nonce)))
                    continue
                if isinstance(inbound, PongFrame):
                    # Answers this node's liveness probe; unsolicited pongs are inert.
                    registry.resolve_probe(parsed.node_id)
                    continue
                if isinstance(inbound, WaitFrame):
                    # Runs as a task so a long wait never blocks the read loop
                    # (telemetry, dispatch, peer messages, ping answers).
                    wait_task = asyncio.create_task(
                        handle_wait(
                            frame=inbound,
                            websocket=websocket,
                            store=store,
                            registry=registry,
                            requester_node_id=parsed.node_id,
                        )
                    )
                    reply_tasks.add(wait_task)
                    wait_task.add_done_callback(reply_tasks.discard)
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
                    # wait_until_delivery can block as long as a run wait; same task treatment.
                    status_task = asyncio.create_task(
                        handle_message_status(
                            frame=inbound,
                            websocket=websocket,
                            store=store,
                            registry=registry,
                            requester_node_id=parsed.node_id,
                        )
                    )
                    reply_tasks.add(status_task)
                    status_task.add_done_callback(reply_tasks.discard)
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
            await _cancel_reply_tasks(reply_tasks)
            # Generation-guarded cleanup: a stale handler (replaced via takeover
            # of a zombie incumbent) must not remove or reap the newer entry.
            if node_id is not None and registry.remove_connection(node_id, generation=connection_generation):
                try:
                    await asyncio.to_thread(store.touch_agent, node_id)
                except sqlite3.Error:
                    # Reaping must still proceed when a best-effort recency write loses a shutdown race.
                    pass
                finally:
                    # The touch above suspends, so re-check: a reconnect that landed
                    # in that window already cancelled its predecessor's reaper, and
                    # scheduling one here would target a live connection.
                    if not registry.has_connection(node_id):
                        schedule_disconnect_reaper(node_id=node_id, registry=registry, store=store)

    return app


async def _incumbent_is_live(incumbent: WebSocket, node_id: str, registry: Registry) -> bool:
    """Classify an incumbent connection by round-tripping a liveness probe.

    A completed write proves nothing: the selected websocket implementation
    buffers into the transport without suspending, so a frozen or half-open
    peer accepts the bytes exactly like a healthy one. Liveness therefore
    requires evidence *from* the peer — a pong echoing this probe's nonce,
    which the client already sends. A send failure means dead outright; a
    silent peer means dead once the timeout elapses.
    """

    probe = PingFrame(type="ping", nonce=uuid4().hex)
    answered = registry.open_probe(node_id)
    try:
        async with asyncio.timeout(_INCUMBENT_PROBE_TIMEOUT_S):
            await incumbent.send_json(serialize_frame(probe))
            await answered
    except asyncio.CancelledError:
        # A concurrent register superseded this probe; that is not a cancellation
        # of this handler, so classify as unproven rather than propagating.
        if answered.cancelled():
            return False
        raise
    except Exception:  # noqa: BLE001 — send failure or unanswered probe reads as dead
        return False
    finally:
        registry.close_probe(node_id)
    return True


async def _cancel_reply_tasks(tasks: set[asyncio.Task[None]]) -> None:
    """Cancel this connection's outstanding reply tasks and await their exit."""

    pending = [task for task in tasks if not task.done()]
    for task in pending:
        task.cancel()
    # gather collects each task's cancellation as a result, while still letting a
    # cancellation aimed at *this* handler propagate rather than being swallowed.
    await asyncio.gather(*pending, return_exceptions=True)


async def _close_websocket_quietly(websocket: WebSocket) -> None:
    try:
        async with asyncio.timeout(_TAKEOVER_CLOSE_TIMEOUT_S):
            await websocket.close(code=1000)
    except Exception:  # noqa: BLE001 — close is best effort; takeover proceeds
        return


async def _send_error_and_close(websocket: WebSocket, *, code: str, message: str) -> None:
    error = ErrorFrame(type="error", code=code, message=message)
    await websocket.send_json(serialize_frame(error))
    await websocket.close(code=1002)
