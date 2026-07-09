"""Peer messaging: acceptance, delivery acks, status waits, public handles."""

from __future__ import annotations

import asyncio
import math
import uuid
from dataclasses import dataclass
from typing import Any

from ..frames import (
    PROTOCOL_VERSION,
    MessageStatusFrame,
    MessageStatusResultFrame,
    PeerMessageAckFrame,
    PeerMessageDeliveryAckFrame,
    PeerMessageDeliveryFrame,
    PeerMessageFrame,
)
from ..registry import MessageWaiter, Registry
from ..store import Store, is_message_delivery_terminal, safe_product_role

DEFAULT_MESSAGE_WAIT_TIMEOUT_SECONDS = 30.0
MAX_MESSAGE_WAIT_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True)
class AcceptedPeerMessage:
    ack: PeerMessageAckFrame
    delivery: PeerMessageDeliveryFrame
    target_agent_id: str


def _sender_product_role(sender: dict[str, Any] | None) -> str | None:
    if sender is None:
        return None
    if sender.get("role") == "agent":
        return safe_product_role(sender.get("agent_type")) or "subagent"
    return safe_product_role(sender.get("product_role")) or None


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
