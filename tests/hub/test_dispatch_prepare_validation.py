"""prepare_dispatch target-validation and retask-handle tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from basecamp.hub.frames import PROTOCOL_VERSION, DispatchFrame, DispatchSpec
from basecamp.hub.store import Store
from basecamp.hub.swarm.service.dispatch import DispatchRejection, PreparedDispatch, prepare_dispatch

pytestmark = pytest.mark.usefixtures("_isolate_run_result_home")


@pytest.mark.asyncio
async def test_prepare_dispatch_preserves_canonical_handle_on_retask_by_id(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="agent",
        session_name="root-session",
        cwd=str(tmp_path),
    )
    store.upsert_agent(
        agent_id="worker-agent",
        agent_handle="amber-otter-111aaa",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="worker",
        session_name="worker-agent",
        cwd=str(tmp_path),
        agent_type="scout",
    )
    store.create_run(
        run_id="run-first",
        agent_id="worker-agent",
        dispatcher_id="root",
        spec={"task": "x"},
        report_token_hash="hash",
    )
    store.set_run_result(run_id="run-first", status="completed", result="done", error=None)

    frame = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="run-retask-by-id",
        agent_id="worker-agent",
        agent_type="scout",
        spec=DispatchSpec(
            argv=["pi", "--mode", "json", "-p"],
            env={},
            cwd=str(tmp_path),
            resume_path=None,
            task="redo work",
        ),
    )

    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id="root",
        store=store,
    )

    assert isinstance(dispatch, PreparedDispatch)
    assert dispatch.agent_handle == "amber-otter-111aaa"
    agent = store.get_agent("worker-agent")
    assert agent is not None
    assert agent["agent_handle"] == "amber-otter-111aaa"


@pytest.mark.asyncio
async def test_prepare_dispatch_rejects_conflicting_handle_rename_on_retask(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="agent",
        session_name="root-session",
        cwd=str(tmp_path),
    )
    store.upsert_agent(
        agent_id="worker-agent",
        agent_handle="amber-otter-111aaa",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="worker",
        session_name="worker-agent",
        cwd=str(tmp_path),
        agent_type="scout",
    )
    store.create_run(
        run_id="run-first",
        agent_id="worker-agent",
        dispatcher_id="root",
        spec={"task": "x"},
        report_token_hash="hash",
    )
    store.set_run_result(run_id="run-first", status="completed", result="done", error=None)

    frame = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="run-rename",
        agent_id="worker-agent",
        agent_handle="mossy-lynx-222bbb",
        agent_type="scout",
        spec=DispatchSpec(
            argv=["pi", "--mode", "json", "-p"],
            env={},
            cwd=str(tmp_path),
            resume_path=None,
            task="redo work",
        ),
    )

    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id="root",
        store=store,
    )

    assert dispatch == DispatchRejection(reason="duplicate_agent_handle")
    assert store.get_run("run-rename") is None
    agent = store.get_agent("worker-agent")
    assert agent is not None
    assert agent["agent_handle"] == "amber-otter-111aaa"


@pytest.mark.asyncio
async def test_prepare_dispatch_rejects_session_as_dispatch_target_by_handle_or_id(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    store.upsert_agent(
        agent_id="root",
        agent_handle="root-handle",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="agent",
        session_name="root-session",
        cwd=str(tmp_path),
    )

    for run_id, dispatch_target in [
        ("run-session-handle", {"agent_handle": "root-handle"}),
        ("run-session-id", {"agent_id": "root"}),
    ]:
        frame = DispatchFrame(
            type="dispatch",
            v=PROTOCOL_VERSION,
            run_id=run_id,
            spec=DispatchSpec(
                argv=["pi", "--mode", "json", "-p"],
                env={},
                cwd=str(tmp_path),
                resume_path=None,
                task="do work",
            ),
            **dispatch_target,
        )

        dispatch = await prepare_dispatch(
            frame=frame,
            dispatcher_node_id="root",
            store=store,
        )

        assert dispatch == DispatchRejection(reason="not_dispatchable")
        assert store.get_run(run_id) is None

    root = store.get_agent("root")
    assert root is not None
    assert root["role"] == "agent"


@pytest.mark.asyncio
async def test_prepare_dispatch_rejects_existing_ask_agent_as_dispatch_target(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="agent",
        session_name="root-session",
        cwd=str(tmp_path),
    )
    store.upsert_agent(
        agent_id="ask-agent",
        agent_handle="ask-handle",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="worker",
        session_name="ask-agent",
        cwd=str(tmp_path),
        agent_type="ask",
    )
    frame = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="run-ask-retask",
        agent_handle="ask-handle",
        spec=DispatchSpec(
            argv=["pi", "--mode", "json", "-p"],
            env={},
            cwd=str(tmp_path),
            resume_path=None,
            task="do work",
        ),
    )

    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id="root",
        store=store,
    )

    assert dispatch == DispatchRejection(reason="not_dispatchable")
    assert store.get_run("run-ask-retask") is None


@pytest.mark.asyncio
async def test_prepare_dispatch_persists_new_agent_sibling_group(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="agent",
        session_name="root-session",
        cwd=str(tmp_path),
    )
    frame = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="run-child",
        agent_id="child-agent",
        spec=DispatchSpec(
            argv=["pi", "--mode", "json", "-p"],
            env={},
            cwd=str(tmp_path),
            resume_path=None,
            task="do work",
        ),
    )

    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id="root",
        store=store,
    )

    assert isinstance(dispatch, PreparedDispatch)
    agent = store.get_agent("child-agent")
    assert agent is not None
    assert agent["sibling_group"] == "root"
