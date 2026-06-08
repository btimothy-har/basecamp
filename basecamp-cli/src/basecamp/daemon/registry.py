"""In-memory connection/run registry for daemon runtime state."""

from __future__ import annotations

import asyncio
from collections.abc import MutableMapping

from fastapi import WebSocket


class Registry:
    """Tracks connected nodes and runtime process ownership mappings."""

    def __init__(self) -> None:
        self._connections: MutableMapping[str, WebSocket] = {}
        self._runs: MutableMapping[str, str] = {}
        self._processes: MutableMapping[str, asyncio.subprocess.Process] = {}

    def set_connection(self, node_id: str, websocket: WebSocket) -> None:
        """Register or replace an active node connection."""

        self._connections[node_id] = websocket

    def remove_connection(self, node_id: str) -> None:
        """Remove a node connection if present."""

        self._connections.pop(node_id, None)

    def get_connection(self, node_id: str) -> WebSocket | None:
        """Look up an active connection by node id."""

        return self._connections.get(node_id)

    def set_run_owner(self, run_id: str, node_id: str) -> None:
        """Associate a run id with a node id."""

        self._runs[run_id] = node_id

    def remove_run_owner(self, run_id: str) -> None:
        """Remove run ownership mapping if present."""

        self._runs.pop(run_id, None)

    def get_run_owner(self, run_id: str) -> str | None:
        """Look up run owner by run id."""

        return self._runs.get(run_id)

    def set_process(self, run_id: str, process: asyncio.subprocess.Process) -> None:
        """Track a subprocess handle for a run."""

        self._processes[run_id] = process

    def pop_process(self, run_id: str) -> asyncio.subprocess.Process | None:
        """Drop and return the tracked process for a run."""

        return self._processes.pop(run_id, None)
