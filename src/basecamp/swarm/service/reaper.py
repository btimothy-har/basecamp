"""Dispatcher-disconnect reaper: fail and terminate orphaned live runs."""

from __future__ import annotations

import asyncio
import os

from ..process import terminate_process_group_if_runner
from ..registry import Registry
from ..store import Store
from .waiting import notify_run_finalized

DEFAULT_DISCONNECT_GRACE_SECONDS = 3600.0


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
        if registry.has_connection(node_id):
            return
        finalized = await asyncio.to_thread(
            store.set_run_result_if_unset,
            run_id=run_id,
            status="failed",
            result=None,
            error="dispatcher_disconnected",
        )
        if not finalized:
            continue
        process = registry.get_process(run_id)
        if process is not None:
            await asyncio.to_thread(terminate_process_group_if_runner, process.pid)
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
