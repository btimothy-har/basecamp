"""Root-scoped agent directory listing."""

from __future__ import annotations

import asyncio
from typing import Any

from ...frames import ListAgentItem, ListAgentsFrame
from ...store import Store


async def list_agents(
    *,
    frame: ListAgentsFrame,
    store: Store,
    requester_node_id: str,
) -> list[ListAgentItem]:
    rows = await asyncio.to_thread(
        store.get_root_agent_directory,
        requester_node_id=requester_node_id,
        awaitable=frame.awaitable,
    )
    items: list[ListAgentItem] = []
    for row in rows:
        values: dict[str, Any] = {
            "agent_id": row["agent_id"],
            "agent_handle": row["agent_handle"],
            "parent_id": row["parent_id"],
            "role": row["role"],
            "session_name": row["session_name"],
            "depth": row["depth"],
            "status": row["status"],
            "awaitable": row["awaitable"],
        }
        if row.get("task") is not None:
            values["task"] = row["task"]
        if row.get("agent_type") is not None:
            values["agent_type"] = row["agent_type"]
        items.append(ListAgentItem(**values))
    return items
