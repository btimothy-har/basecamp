"""Disconnect-reaper and orphaned-run reconciliation tests."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from dispatch_helpers import _FakePidProcess

from basecamp.hub.process import reconcile_orphaned_runs
from basecamp.hub.registry import Registry, Waiter
from basecamp.hub.service.reaper import (
    DEFAULT_DISCONNECT_GRACE_SECONDS,
    _resolve_disconnect_grace_s,
    _run_disconnect_reaper,
    schedule_disconnect_reaper,
)
from basecamp.hub.store import Store

pytestmark = pytest.mark.usefixtures("_isolate_run_result_home")


def test_registry_live_run_ids_for_owner_returns_only_owned_runs_with_processes() -> None:
    registry = Registry()
    registry.set_run_owner("owned-live", "node-1")
    registry.set_run_owner("owned-no-process", "node-1")
    registry.set_run_owner("other-live", "node-2")
    registry.set_process("owned-live", _FakePidProcess(123))
    registry.set_process("other-live", _FakePidProcess(456))

    assert registry.live_run_ids_for_owner("node-1") == ["owned-live"]


@pytest.mark.asyncio
async def test_registry_set_disconnect_reaper_cancels_prior_reaper() -> None:
    registry = Registry()
    first = asyncio.create_task(asyncio.sleep(1000))
    second = asyncio.create_task(asyncio.sleep(1000))

    registry.set_disconnect_reaper("node-1", first)
    registry.set_disconnect_reaper("node-1", second)
    await asyncio.sleep(0)

    assert first.cancelled()
    assert not second.cancelled()
    registry.cancel_disconnect_reaper("node-1")
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_registry_discard_disconnect_reaper_only_removes_matching_task() -> None:
    registry = Registry()
    stored = asyncio.create_task(asyncio.sleep(1000))
    other = asyncio.create_task(asyncio.sleep(1000))
    registry.set_disconnect_reaper("node-1", stored)

    registry.discard_disconnect_reaper("node-1", other)
    registry.cancel_disconnect_reaper("node-1")
    await asyncio.sleep(0)

    assert stored.cancelled()
    assert not other.cancelled()
    other.cancel()
    await asyncio.sleep(0)


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        (None, DEFAULT_DISCONNECT_GRACE_SECONDS),
        ("12.5", 12.5),
        ("not-a-number", DEFAULT_DISCONNECT_GRACE_SECONDS),
        ("-1", DEFAULT_DISCONNECT_GRACE_SECONDS),
    ],
)
def test_resolve_disconnect_grace_s(
    env_value: str | None,
    expected: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if env_value is None:
        monkeypatch.delenv("BASECAMP_AGENT_DISCONNECT_GRACE_S", raising=False)
    else:
        monkeypatch.setenv("BASECAMP_AGENT_DISCONNECT_GRACE_S", env_value)

    assert _resolve_disconnect_grace_s() == expected


@pytest.mark.asyncio
async def test_disconnect_reaper_marks_live_run_failed_terminates_process_and_wakes_waiter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    registry = Registry()
    run_id = "run-disconnected"
    terminated: list[int | None] = []

    def record_terminate(pgid: int | None, **_kwargs: object) -> None:
        terminated.append(pgid)

    monkeypatch.setattr("basecamp.hub.service.reaper.terminate_process_group_if_runner", record_terminate)
    store.create_run(run_id=run_id, agent_id="agent-disconnected", dispatcher_id="node-1", spec={})
    store.set_run_pgid(run_id=run_id, pgid=4321)
    registry.set_run_owner(run_id, "node-1")
    registry.set_process(run_id, _FakePidProcess(4321))
    waiter = Waiter(
        waiter_id="waiter-1",
        run_ids={run_id},
        future=asyncio.get_running_loop().create_future(),
    )
    registry.add_waiter(waiter)

    await _run_disconnect_reaper(node_id="node-1", registry=registry, store=store, grace_s=0)

    run = store.get_run(run_id)
    assert run is not None
    assert run["status"] == "failed"
    assert run["result"] is None
    assert run["error"] == "dispatcher_disconnected"
    assert terminated == [4321]
    assert waiter.future.done()


@pytest.mark.asyncio
async def test_disconnect_reaper_cancel_prevents_reap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    registry = Registry()
    terminated: list[int | None] = []
    monkeypatch.setattr(
        "basecamp.hub.service.reaper.terminate_process_group_if_runner",
        lambda pgid, **_kwargs: terminated.append(pgid),
    )
    store.create_run(run_id="run-still-live", agent_id="agent-still-live", dispatcher_id="node-1", spec={})
    registry.set_run_owner("run-still-live", "node-1")
    registry.set_process("run-still-live", _FakePidProcess(4321))

    schedule_disconnect_reaper(node_id="node-1", registry=registry, store=store, grace_s=1000)
    task = registry._disconnect_reapers["node-1"]
    registry.cancel_disconnect_reaper("node-1")
    await asyncio.sleep(0)

    assert task.cancelled()
    assert store.get_run("run-still-live")["status"] == "running"
    assert terminated == []


@pytest.mark.asyncio
async def test_disconnect_reaper_no_live_runs_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    registry = Registry()
    terminated: list[int | None] = []
    monkeypatch.setattr(
        "basecamp.hub.service.reaper.terminate_process_group_if_runner",
        lambda pgid, **_kwargs: terminated.append(pgid),
    )
    store.create_run(run_id="run-no-process", agent_id="agent-no-process", dispatcher_id="node-1", spec={})
    registry.set_run_owner("run-no-process", "node-1")

    await _run_disconnect_reaper(node_id="node-1", registry=registry, store=store, grace_s=0)

    run = store.get_run("run-no-process")
    assert run is not None
    assert run["status"] == "running"
    assert terminated == []


@pytest.mark.asyncio
async def test_disconnect_reaper_skips_termination_when_run_already_finalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    registry = Registry()
    terminated: list[int | None] = []
    monkeypatch.setattr(
        "basecamp.hub.service.reaper.terminate_process_group_if_runner",
        lambda pgid, **_kwargs: terminated.append(pgid),
    )
    store.create_run(run_id="run-terminal", agent_id="agent-terminal", dispatcher_id="node-1", spec={})
    store.set_run_result(run_id="run-terminal", status="completed", result="done", error=None)
    registry.set_run_owner("run-terminal", "node-1")
    registry.set_process("run-terminal", _FakePidProcess(4321))

    await _run_disconnect_reaper(node_id="node-1", registry=registry, store=store, grace_s=0)

    assert store.get_run("run-terminal")["status"] == "completed"
    assert terminated == []


@pytest.mark.asyncio
async def test_disconnect_reaper_mid_loop_reconnect_stops_reaping_remaining_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    registry = Registry()
    terminated: list[int | None] = []
    original_set_run_result_if_unset = store.set_run_result_if_unset

    def record_terminate(pgid: int | None, **_kwargs: object) -> None:
        terminated.append(pgid)

    def reconnect_after_first_finalize(**kwargs: object) -> bool:
        finalized = original_set_run_result_if_unset(**kwargs)
        registry.set_connection("node-1", object())
        return finalized

    monkeypatch.setattr("basecamp.hub.service.reaper.terminate_process_group_if_runner", record_terminate)
    monkeypatch.setattr(store, "set_run_result_if_unset", reconnect_after_first_finalize)
    store.create_run(run_id="run-first", agent_id="agent-first", dispatcher_id="node-1", spec={})
    store.create_run(run_id="run-second", agent_id="agent-second", dispatcher_id="node-1", spec={})
    registry.set_run_owner("run-first", "node-1")
    registry.set_run_owner("run-second", "node-1")
    registry.set_process("run-first", _FakePidProcess(1111))
    registry.set_process("run-second", _FakePidProcess(2222))

    await _run_disconnect_reaper(node_id="node-1", registry=registry, store=store, grace_s=0)

    assert store.get_run("run-first")["status"] == "failed"
    assert store.get_run("run-second")["status"] == "running"
    assert terminated == [1111]


def test_reconcile_orphaned_runs_marks_nonterminal_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    store.create_run(run_id="run-running", agent_id="agent-running", dispatcher_id="root", spec={})
    store.create_run(run_id="run-pending", agent_id="agent-pending", dispatcher_id="root", spec={})
    with sqlite3.connect(tmp_path / "daemon.db") as connection:
        connection.execute("UPDATE runs SET status = 'pending' WHERE id = ?", ("run-pending",))
    store.set_run_pgid(run_id="run-running", pgid=321)
    store.set_run_pgid(run_id="run-pending", pgid=654)
    monkeypatch.setattr("basecamp.hub.process._process_group_is_runner", lambda _pgid: False)

    reconcile_orphaned_runs(store)

    for run_id in ["run-running", "run-pending"]:
        run = store.get_run(run_id)
        assert run is not None
        assert run["status"] == "failed"
        assert run["result"] is None
        assert run["error"] == "daemon_restart_reconciled"


def test_reconcile_orphaned_runs_kills_verified_runner_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    store.create_run(run_id="run-orphan", agent_id="agent-orphan", dispatcher_id="root", spec={})
    store.set_run_pgid(run_id="run-orphan", pgid=4321)
    calls: list[tuple[int, float, float]] = []

    def record_terminate(pgid: int | None, *, escalation_s: float = 5.0, poll_s: float = 0.1) -> None:
        calls.append((pgid or 0, escalation_s, poll_s))

    monkeypatch.setattr("basecamp.hub.process.terminate_process_group_if_runner", record_terminate)

    reconcile_orphaned_runs(store)

    assert calls == [(4321, 2.0, 0.1)]
    run = store.get_run("run-orphan")
    assert run is not None
    assert run["status"] == "failed"
    assert run["error"] == "daemon_restart_reconciled"


def test_reconcile_orphaned_runs_skips_unverified_group_but_marks_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    store.create_run(run_id="run-mismatch", agent_id="agent-mismatch", dispatcher_id="root", spec={})
    store.set_run_pgid(run_id="run-mismatch", pgid=4321)
    calls: list[int | None] = []

    def record_terminate(pgid: int | None, **_kwargs: object) -> None:
        calls.append(pgid)

    monkeypatch.setattr("basecamp.hub.process._process_group_is_runner", lambda _pgid: False)
    monkeypatch.setattr("basecamp.hub.process.terminate_process_group", record_terminate)

    reconcile_orphaned_runs(store)

    assert calls == []
    run = store.get_run("run-mismatch")
    assert run is not None
    assert run["status"] == "failed"
    assert run["error"] == "daemon_restart_reconciled"
