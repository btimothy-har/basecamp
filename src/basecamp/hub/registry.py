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
        self._pending_probes: MutableMapping[str, asyncio.Future[None]] = {}
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

    def claim_connection(self, node_id: str, websocket: object, *, replacing: int | None) -> int | None:
        """Atomically claim a node id, returning the new generation or None.

        ``replacing`` is the generation observed before the caller awaited its
        liveness probe: the claim lands only if that entry is still registered
        (or, for ``None``, if the id is still unheld). Probing suspends, so a
        second registration can settle in between — without this compare-and-set
        both would call ``set_connection`` and the loser would keep serving
        frames while invisible to routing and to its own cleanup guard.
        """

        entry = self._connections.get(node_id)
        current = entry[1] if entry is not None else None
        if current != replacing:
            return None
        return self.set_connection(node_id, websocket)

    def remove_connection(self, node_id: str, *, generation: int) -> bool:
        """Remove a node connection if the registered entry is still this one.

        Returns True when the removal landed; a newer entry is left alone and
        returns False, so a stale handler cannot clear its successor.
        """

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

    def open_probe(self, node_id: str) -> asyncio.Future[None]:
        """Arm a liveness probe for a node, replacing any probe already pending."""

        self.close_probe(node_id)
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._pending_probes[node_id] = future
        return future

    def resolve_probe(self, node_id: str) -> None:
        """Answer a node's pending liveness probe, if one is armed."""

        future = self._pending_probes.get(node_id)
        if future is not None and not future.done():
            future.set_result(None)

    def close_probe(self, node_id: str) -> None:
        """Drop a node's pending probe, cancelling it if still unanswered."""

        future = self._pending_probes.pop(node_id, None)
        if future is not None and not future.done():
            future.cancel()

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
