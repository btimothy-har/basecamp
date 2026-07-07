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


@dataclass
class MessageWaiter:
    """In-memory wait registration for one peer-message id."""

    waiter_id: str
    message_id: str
    future: asyncio.Future[None]


class Registry:
    """Tracks runtime connections, run ownership/processes, and waiters."""

    def __init__(self) -> None:
        self._connections: MutableMapping[str, object] = {}
        self._runs: MutableMapping[str, str] = {}
        self._processes: MutableMapping[str, asyncio.subprocess.Process] = {}
        self._disconnect_reapers: MutableMapping[str, asyncio.Task[None]] = {}
        self._waiters: MutableMapping[str, Waiter] = {}
        self._message_waiters: MutableMapping[str, MessageWaiter] = {}

    def set_connection(self, node_id: str, websocket: object) -> None:
        """Register or replace an active node connection."""

        self._connections[node_id] = websocket

    def remove_connection(self, node_id: str) -> None:
        """Remove a node connection if present."""

        self._connections.pop(node_id, None)

    def get_connection(self, node_id: str) -> object | None:
        """Look up an active connection by node id."""

        return self._connections.get(node_id)

    def has_connection(self, node_id: str) -> bool:
        """Return whether a node id has an active websocket connection."""

        return node_id in self._connections

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

    def get_process(self, run_id: str) -> asyncio.subprocess.Process | None:
        """Look up a tracked subprocess handle without removing it."""

        return self._processes.get(run_id)

    def pop_process(self, run_id: str) -> asyncio.subprocess.Process | None:
        """Drop and return the tracked process for a run."""

        return self._processes.pop(run_id, None)

    def live_run_ids_for_owner(self, node_id: str) -> list[str]:
        """Return owned run ids that still have tracked live subprocess handles."""

        return [run_id for run_id, owner in self._runs.items() if owner == node_id and run_id in self._processes]

    def set_disconnect_reaper(self, node_id: str, task: asyncio.Task[None]) -> None:
        """Register a disconnect reaper task, cancelling any previous one."""

        existing = self._disconnect_reapers.get(node_id)
        if existing is not None:
            existing.cancel()
        self._disconnect_reapers[node_id] = task

    def cancel_disconnect_reaper(self, node_id: str) -> None:
        """Cancel and remove a disconnect reaper task if present."""

        task = self._disconnect_reapers.pop(node_id, None)
        if task is not None:
            task.cancel()

    def discard_disconnect_reaper(self, node_id: str, task: asyncio.Task[None]) -> None:
        """Remove a disconnect reaper only if it is still the registered task."""

        if self._disconnect_reapers.get(node_id) is task:
            self._disconnect_reapers.pop(node_id, None)

    def add_waiter(self, waiter: Waiter) -> None:
        """Register a waiter by id."""

        self._waiters[waiter.waiter_id] = waiter

    def remove_waiter(self, waiter_id: str) -> None:
        """Remove waiter registration by id if present."""

        self._waiters.pop(waiter_id, None)

    def list_waiters(self) -> list[Waiter]:
        """Return a snapshot of active waiters."""

        return list(self._waiters.values())

    def add_message_waiter(self, waiter: MessageWaiter) -> None:
        """Register a peer-message waiter by id."""

        self._message_waiters[waiter.waiter_id] = waiter

    def remove_message_waiter(self, waiter_id: str) -> None:
        """Remove peer-message waiter registration by id if present."""

        self._message_waiters.pop(waiter_id, None)

    def list_message_waiters(self) -> list[MessageWaiter]:
        """Return a snapshot of active peer-message waiters."""

        return list(self._message_waiters.values())
