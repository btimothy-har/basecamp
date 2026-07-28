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
        self._connections: MutableMapping[str, tuple[object, int]] = {}
        self._next_generation = 0
        self._runs: MutableMapping[str, str] = {}
        self._processes: MutableMapping[str, asyncio.subprocess.Process] = {}
        self._disconnect_reapers: MutableMapping[str, asyncio.Task[None]] = {}
        self._waiters: MutableMapping[str, Waiter] = {}
        self._message_waiters: MutableMapping[str, MessageWaiter] = {}

    def set_connection(self, node_id: str, websocket: object) -> int:
        """Register or replace an active node connection; returns its generation.

        The generation is a monotonic per-registry stamp that lets a handler
        prove the registered entry is still its own before mutating it — a
        stale handler (replaced by a same-node re-registration) must never
        remove or reap the newer connection.
        """

        self._next_generation += 1
        self._connections[node_id] = (websocket, self._next_generation)
        return self._next_generation

    def remove_connection(self, node_id: str, *, generation: int | None = None) -> bool:
        """Remove a node connection, optionally generation-guarded.

        With a generation, the removal only lands when the registered entry is
        still that exact connection (returns True); a newer entry is left alone
        (returns False). Without one, removes unconditionally (legacy caller).
        """

        if generation is None:
            self._connections.pop(node_id, None)
            return True
        entry = self._connections.get(node_id)
        if entry is None or entry[1] != generation:
            return False
        del self._connections[node_id]
        return True

    def get_connection(self, node_id: str) -> object | None:
        """Look up an active connection by node id."""

        entry = self._connections.get(node_id)
        return entry[0] if entry is not None else None

    def get_connection_generation(self, node_id: str) -> int | None:
        """Look up the generation of the active connection, if any."""

        entry = self._connections.get(node_id)
        return entry[1] if entry is not None else None

    def is_connection_current(self, node_id: str, generation: int) -> bool:
        """True when the registered entry for node id is exactly this generation."""

        entry = self._connections.get(node_id)
        return entry is not None and entry[1] == generation

    def has_connection(self, node_id: str) -> bool:
        """Return whether a node id has an active websocket connection."""

        return node_id in self._connections

    def live_node_ids(self) -> set[str]:
        """Return the set of node ids with a live websocket connection."""

        return set(self._connections.keys())

    def set_run_owner(self, run_id: str, node_id: str) -> None:
        """Associate a run id with a node id."""

        self._runs[run_id] = node_id

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
