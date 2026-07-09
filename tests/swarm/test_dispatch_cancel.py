"""cancel_agent authorization and subtree cancellation tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from basecamp.swarm.frames import PROTOCOL_VERSION, CancelFrame
from basecamp.swarm.registry import Registry, Waiter
from basecamp.swarm.service import cancel_agent
from basecamp.swarm.store import Store
from dispatch_helpers import _create_live_run, _FakePidProcess, _upsert_test_agent

pytestmark = pytest.mark.usefixtures("_isolate_run_result_home")


@pytest.mark.asyncio
async def test_cancel_agent_unknown_handle_returns_not_found(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    registry = Registry()

    ack = await cancel_agent(
        frame=CancelFrame(
            type="cancel",
            v=PROTOCOL_VERSION,
            request_id="cancel-missing",
            target_handle="missing-handle",
        ),
        requester_node_id="root",
        store=store,
        registry=registry,
    )

    assert ack.type == "cancel_ack"
    assert ack.request_id == "cancel-missing"
    assert ack.status == "not_found"
    assert ack.error is None


@pytest.mark.asyncio
async def test_cancel_agent_known_but_unauthorized_returns_not_authorized(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    registry = Registry()
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="outside-agent",
        agent_handle="outside-handle",
        parent_id=None,
        sibling_group=None,
        depth=1,
        role="agent",
        session_name="outside-agent",
        cwd="/tmp/outside",
    )

    ack = await cancel_agent(
        frame=CancelFrame(
            type="cancel",
            v=PROTOCOL_VERSION,
            request_id="cancel-unauthorized",
            target_handle="outside-handle",
        ),
        requester_node_id="root",
        store=store,
        registry=registry,
    )

    assert ack.status == "not_authorized"
    assert ack.error is None


@pytest.mark.parametrize("run_state", ["none", "terminal"])
@pytest.mark.asyncio
async def test_cancel_agent_authorized_without_live_run_returns_already_terminal(
    tmp_path: Path,
    run_state: str,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    registry = Registry()
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="child-agent",
        agent_handle="child-handle",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="child-agent",
        cwd="/tmp/child",
    )
    if run_state == "terminal":
        store.create_run(
            run_id="run-terminal",
            agent_id="child-agent",
            dispatcher_id="root",
            spec={"task": "done"},
            report_token_hash="hash",
        )
        store.set_run_result(
            run_id="run-terminal",
            status="completed",
            result="done",
            error=None,
        )

    ack = await cancel_agent(
        frame=CancelFrame(
            type="cancel",
            v=PROTOCOL_VERSION,
            request_id="cancel-terminal",
            target_handle="child-handle",
        ),
        requester_node_id="root",
        store=store,
        registry=registry,
    )

    assert ack.status == "already_terminal"
    assert ack.error is None


@pytest.mark.asyncio
async def test_cancel_agent_authorized_live_run_fails_run_terminates_process_and_wakes_waiter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    registry = Registry()
    terminated: list[int | None] = []

    def record_terminate(pgid: int | None, **_kwargs: object) -> None:
        terminated.append(pgid)

    monkeypatch.setattr("basecamp.swarm.service.cancel.terminate_process_group_if_runner", record_terminate)
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="child-agent",
        agent_handle="child-handle",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="child-agent",
        cwd="/tmp/child",
    )
    store.create_run(
        run_id="run-live",
        agent_id="child-agent",
        dispatcher_id="root",
        spec={"task": "running"},
        report_token_hash="hash",
    )
    registry.set_process("run-live", _FakePidProcess(4321))
    waiter = Waiter(
        waiter_id="waiter-cancel",
        run_ids={"run-live"},
        future=asyncio.get_running_loop().create_future(),
    )
    registry.add_waiter(waiter)

    ack = await cancel_agent(
        frame=CancelFrame(
            type="cancel",
            v=PROTOCOL_VERSION,
            request_id="cancel-live",
            target_handle="child-handle",
        ),
        requester_node_id="root",
        store=store,
        registry=registry,
    )

    run = store.get_run("run-live")
    assert ack.status == "cancelled"
    assert ack.error is None
    assert run is not None
    assert run["status"] == "failed"
    assert run["result"] is None
    assert run["error"] == "cancelled"
    assert terminated == [4321]
    assert waiter.future.done()


@pytest.mark.asyncio
async def test_cancel_agent_recursively_cancels_live_subtree_runs_and_wakes_waiters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    registry = Registry()
    terminated: list[int | None] = []

    def record_terminate(pgid: int | None, **_kwargs: object) -> None:
        terminated.append(pgid)

    monkeypatch.setattr("basecamp.swarm.service.cancel.terminate_process_group_if_runner", record_terminate)
    _upsert_test_agent(store, agent_id="root", parent_id=None, depth=0, role="session")
    _upsert_test_agent(store, agent_id="target", agent_handle="target-handle", parent_id="root", depth=1)
    _upsert_test_agent(store, agent_id="child", parent_id="target", depth=2)
    _upsert_test_agent(store, agent_id="grandchild", parent_id="child", depth=3)
    _create_live_run(store, registry, agent_id="target", run_id="run-target", dispatcher_id="root", pid=1001)
    _create_live_run(store, registry, agent_id="child", run_id="run-child", dispatcher_id="target", pid=1002)
    _create_live_run(
        store,
        registry,
        agent_id="grandchild",
        run_id="run-grandchild",
        dispatcher_id="child",
        pid=1003,
    )
    waiters = [
        Waiter(
            waiter_id=f"waiter-{run_id}",
            run_ids={run_id},
            future=asyncio.get_running_loop().create_future(),
        )
        for run_id in ["run-target", "run-child", "run-grandchild"]
    ]
    for waiter in waiters:
        registry.add_waiter(waiter)

    ack = await cancel_agent(
        frame=CancelFrame(
            type="cancel",
            v=PROTOCOL_VERSION,
            request_id="cancel-subtree",
            target_handle="target-handle",
        ),
        requester_node_id="root",
        store=store,
        registry=registry,
    )

    assert ack.status == "cancelled"
    assert ack.error is None
    for run_id in ["run-target", "run-child", "run-grandchild"]:
        run = store.get_run(run_id)
        assert run is not None
        assert run["status"] == "failed"
        assert run["result"] is None
        assert run["error"] == "cancelled"
    assert terminated == [1001, 1002, 1003]
    assert all(waiter.future.done() for waiter in waiters)


@pytest.mark.asyncio
async def test_cancel_agent_terminal_target_with_live_descendant_returns_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    registry = Registry()
    terminated: list[int | None] = []

    def record_terminate(pgid: int | None, **_kwargs: object) -> None:
        terminated.append(pgid)

    monkeypatch.setattr("basecamp.swarm.service.cancel.terminate_process_group_if_runner", record_terminate)
    _upsert_test_agent(store, agent_id="root", parent_id=None, depth=0, role="session")
    _upsert_test_agent(store, agent_id="target", agent_handle="target-handle", parent_id="root", depth=1)
    _upsert_test_agent(store, agent_id="child", parent_id="target", depth=2)
    store.create_run(
        run_id="run-target-terminal",
        agent_id="target",
        dispatcher_id="root",
        spec={"task": "done"},
        report_token_hash="hash",
    )
    store.set_run_result(run_id="run-target-terminal", status="completed", result="done", error=None)
    _create_live_run(store, registry, agent_id="child", run_id="run-child-live", dispatcher_id="target", pid=2002)

    ack = await cancel_agent(
        frame=CancelFrame(
            type="cancel",
            v=PROTOCOL_VERSION,
            request_id="cancel-descendant",
            target_handle="target-handle",
        ),
        requester_node_id="root",
        store=store,
        registry=registry,
    )

    child_run = store.get_run("run-child-live")
    target_run = store.get_run("run-target-terminal")
    assert ack.status == "cancelled"
    assert child_run is not None
    assert child_run["status"] == "failed"
    assert child_run["error"] == "cancelled"
    assert target_run is not None
    assert target_run["status"] == "completed"
    assert terminated == [2002]
