"""In-memory connection/run registry for daemon runtime state."""

from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
from dataclasses import dataclass


@dataclass
class Waiter:
    """In-memory wait registration for a run-id set."""

    waiter_id: str
    run_ids: set[str]
    future: asyncio.Future[None]


class Registry:
    """Tracks runtime connections, run ownership/processes, and waiters."""

    def __init__(self) -> None:
        self._connections: MutableMapping[str, object] = {}
        self._runs: MutableMapping[str, str] = {}
        self._processes: MutableMapping[str, asyncio.subprocess.Process] = {}
        self._waiters: MutableMapping[str, Waiter] = {}

    def set_connection(self, node_id: str, websocket: object) -> None:
        """Register or replace an active node connection."""

        self._connections[node_id] = websocket

    def remove_connection(self, node_id: str) -> None:
        """Remove a node connection if present."""

        self._connections.pop(node_id, None)

    def get_connection(self, node_id: str) -> object | None:
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

    def add_waiter(self, waiter: Waiter) -> None:
        """Register a waiter by id."""

        self._waiters[waiter.waiter_id] = waiter

    def remove_waiter(self, waiter_id: str) -> None:
        """Remove waiter registration by id if present."""

        self._waiters.pop(waiter_id, None)

    def list_waiters(self) -> list[Waiter]:
        """Return a snapshot of active waiters."""

        return list(self._waiters.values())
