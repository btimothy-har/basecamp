"""Per-frame websocket handlers for the hub daemon's /ws endpoint.

Split out of app.py along the frame-dispatch seam: app.py owns the connection
lifecycle (registration, liveness-gated takeover, cleanup); these handlers own
what each inbound frame does once the connection is live.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

from .frames import (
    AttachWorkstreamAgentFrame,
    CancelFrame,
    CreateWorkstreamFrame,
    DispatchAckFrame,
    DispatchFrame,
    ListAgentsFrame,
    ListAgentsResultFrame,
    MessageStatusFrame,
    MessageStatusResultFrame,
    PeerMessageDeliveryFrame,
    PeerMessageFrame,
    ReviseWorkstreamFrame,
    UpdateWorkstreamFrame,
    WaitFrame,
    WaitResultFrame,
    WaitResultItem,
    serialize_frame,
)
from .registry import Registry
from .store import Store
from .swarm.service import (
    AcceptedPeerMessage,
    accept_peer_message,
    attach_workstream_agent,
    cancel_agent,
    create_workstream,
    dispatch_agent,
    list_agents,
    message_status_result,
    notify_message_delivery_terminal,
    revise_workstream,
    update_workstream,
    wait_for_agents,
)

logger = logging.getLogger(__name__)


async def _send_reply(websocket: WebSocket, frame: object) -> None:
    """Write a deferred reply, tolerating a requester that already went away.

    Waits and delivery-status waits resolve on their own schedule, so the socket
    they answer may be gone by then — exactly the long-running case this exists
    for. The awaited work is already done and recorded; only the reply is lost.
    """

    try:
        await websocket.send_json(serialize_frame(frame))
    except Exception:  # noqa: BLE001 — a dead requester is not an error worth raising
        return


async def handle_dispatch(
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
    await websocket.send_json(
        serialize_frame(
            DispatchAckFrame(
                type="dispatch_ack",
                run_id=frame.run_id,
                status=ack.status,
                reason=ack.reason,
            )
        )
    )


async def handle_wait(
    *,
    frame: WaitFrame,
    websocket: WebSocket,
    store: Store,
    registry: Registry,
    requester_node_id: str,
) -> None:
    try:
        results = await wait_for_agents(
            frame=frame,
            store=store,
            registry=registry,
            requester_node_id=requester_node_id,
        )
    except Exception as exc:  # noqa: BLE001 — the requester must still get a correlated reply
        logger.exception("wait failed; reporting unknown for all requested handles")
        message = f"wait failed: {exc}"
        results = [
            WaitResultItem(agent_handle=agent_handle, status="unknown", result=None, error=message)
            for agent_handle in frame.agent_handles
        ] + [
            WaitResultItem(agent_id=agent_id, status="unknown", result=None, error=message)
            for agent_id in frame.agent_ids
        ]
    await _send_reply(
        websocket,
        WaitResultFrame(type="wait_result", request_id=frame.request_id, results=results),
    )


async def handle_list_agents(
    *,
    frame: ListAgentsFrame,
    websocket: WebSocket,
    store: Store,
    registry: Registry,
    requester_node_id: str,
) -> None:
    result = ListAgentsResultFrame(
        type="list_agents_result",
        request_id=frame.request_id,
        agents=await list_agents(
            frame=frame,
            store=store,
            requester_node_id=requester_node_id,
            live_node_ids=registry.live_node_ids(),
        ),
    )
    await websocket.send_json(serialize_frame(result))


async def handle_peer_message(
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


async def handle_message_status(
    *,
    frame: MessageStatusFrame,
    websocket: WebSocket,
    store: Store,
    registry: Registry,
    requester_node_id: str,
) -> None:
    try:
        result = await message_status_result(
            frame=frame,
            requester_node_id=requester_node_id,
            store=store,
            registry=registry,
        )
    except Exception:  # noqa: BLE001 — the requester must still get a correlated reply
        result = MessageStatusResultFrame(
            type="message_status_result",
            request_id=frame.request_id,
            message_id=frame.message_id,
            status="unknown",
            error=None,
            created_at=None,
            sent_at=None,
            queued_at=None,
            failed_at=None,
        )
    await _send_reply(websocket, result)


async def handle_cancel(
    *,
    frame: CancelFrame,
    websocket: WebSocket,
    store: Store,
    registry: Registry,
    requester_node_id: str,
) -> None:
    await websocket.send_json(
        serialize_frame(
            await cancel_agent(
                frame=frame,
                requester_node_id=requester_node_id,
                store=store,
                registry=registry,
            )
        )
    )


async def handle_create_workstream(*, frame: CreateWorkstreamFrame, websocket: WebSocket, store: Store) -> None:
    await websocket.send_json(serialize_frame(await create_workstream(frame=frame, store=store)))


async def handle_attach_workstream_agent(
    *,
    frame: AttachWorkstreamAgentFrame,
    websocket: WebSocket,
    store: Store,
    requester_node_id: str,
) -> None:
    await websocket.send_json(
        serialize_frame(
            await attach_workstream_agent(
                frame=frame,
                requester_node_id=requester_node_id,
                store=store,
            )
        )
    )


async def handle_update_workstream(*, frame: UpdateWorkstreamFrame, websocket: WebSocket, store: Store) -> None:
    await websocket.send_json(serialize_frame(await update_workstream(frame=frame, store=store)))


async def handle_revise_workstream(*, frame: ReviseWorkstreamFrame, websocket: WebSocket, store: Store) -> None:
    await websocket.send_json(serialize_frame(await revise_workstream(frame=frame, store=store)))
