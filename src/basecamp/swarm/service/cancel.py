"""Cancel an agent's current run subtree."""

from __future__ import annotations

import asyncio
from typing import Literal

from ..frames import PROTOCOL_VERSION, CancelAckFrame, CancelFrame
from ..process import terminate_process_group_if_runner
from ..registry import Registry
from ..store import Store
from .waiting import notify_run_finalized


def _cancel_ack(
    request_id: str,
    status: Literal["cancelled", "not_found", "not_authorized", "already_terminal"],
    error: str | None = None,
) -> CancelAckFrame:
    return CancelAckFrame(
        type="cancel_ack",
        v=PROTOCOL_VERSION,
        request_id=request_id,
        status=status,
        error=error,
    )


async def _cancel_agent_run(agent_id: str, *, store: Store, registry: Registry) -> bool:
    agent = await asyncio.to_thread(store.get_agent, agent_id)
    run_id = agent.get("current_run_id") if agent else None
    if not isinstance(run_id, str):
        return False
    finalized = await asyncio.to_thread(
        store.set_run_result_if_unset,
        run_id=run_id,
        status="failed",
        result=None,
        error="cancelled",
    )
    if not finalized:
        return False
    process = registry.get_process(run_id)
    if process is not None:
        await asyncio.to_thread(terminate_process_group_if_runner, process.pid)
    await notify_run_finalized(run_id, registry=registry, store=store)
    return True


async def cancel_agent(
    *,
    frame: CancelFrame,
    requester_node_id: str,
    store: Store,
    registry: Registry,
) -> CancelAckFrame:
    """Authorize and cancel an agent's current run subtree."""

    target = await asyncio.to_thread(store.get_agent_by_handle, frame.target_handle)
    target_agent_id = target.get("id") if target else None
    if not isinstance(target_agent_id, str):
        return _cancel_ack(frame.request_id, "not_found")

    if not await asyncio.to_thread(store.can_cancel, requester_node_id, target_agent_id):
        return _cancel_ack(frame.request_id, "not_authorized")

    subtree_ids = await asyncio.to_thread(store.get_subtree_agent_ids, target_agent_id)
    cancelled_any = False
    for agent_id in subtree_ids:
        if await _cancel_agent_run(agent_id, store=store, registry=registry):
            cancelled_any = True
    return _cancel_ack(frame.request_id, "cancelled" if cancelled_any else "already_terminal")
