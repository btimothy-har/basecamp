"""prepare_dispatch fork-source resolution tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from dispatch_helpers import _write_agent_session_file

from basecamp.swarm.frames import PROTOCOL_VERSION, DispatchFrame, DispatchSpec
from basecamp.swarm.service.dispatch import DispatchRejection, PreparedDispatch, prepare_dispatch
from basecamp.swarm.store import Store

pytestmark = pytest.mark.usefixtures("_isolate_run_result_home")


@pytest.mark.asyncio
async def test_prepare_dispatch_resolves_fork_from_target_handle(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    home = tmp_path / "home"
    session_file = _write_agent_session_file(home, "target-agent")
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd=str(tmp_path),
    )
    store.upsert_agent(
        agent_id="target-agent",
        agent_handle="target-handle",
        parent_id="root",
        sibling_group="sg-target",
        depth=1,
        role="agent",
        session_name="target-agent",
        cwd=str(tmp_path),
    )
    frame = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="run-answerer",
        agent_id="answerer-agent",
        spec=DispatchSpec(
            argv=["pi", "--mode", "json", "-p"],
            env={"HOME": str(home)},
            cwd=str(tmp_path),
            resume_path=None,
            fork_from="target-handle",
            task="question?",
        ),
    )

    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id="root",
        store=store,
    )

    assert isinstance(dispatch, PreparedDispatch)
    assert dispatch.fork_source_path == str(session_file.resolve())
    agent = store.get_agent("answerer-agent")
    assert agent is not None
    assert agent["sibling_group"] == "root"


@pytest.mark.asyncio
async def test_prepare_dispatch_resolves_fork_from_session_handle(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    home = tmp_path / "home"
    session_file = _write_agent_session_file(home, "root")
    store.upsert_agent(
        agent_id="root",
        agent_handle="root-handle",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root-session",
        cwd=str(tmp_path),
    )
    store.upsert_agent(
        agent_id="child-agent",
        agent_handle="child-handle",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="child-agent",
        cwd=str(tmp_path),
    )
    frame = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="run-answerer",
        agent_id="answerer-agent",
        spec=DispatchSpec(
            argv=["pi", "--mode", "json", "-p"],
            env={"HOME": str(home)},
            cwd=str(tmp_path),
            resume_path=None,
            fork_from="root-handle",
            task="question?",
        ),
    )

    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id="child-agent",
        store=store,
    )

    assert isinstance(dispatch, PreparedDispatch)
    assert dispatch.fork_source_path == str(session_file.resolve())
    assert store.get_run("run-answerer") is not None


@pytest.mark.asyncio
async def test_prepare_dispatch_resolves_fork_from_registered_external_session_file(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    session_file = tmp_path / "external-session.jsonl"
    session_file.write_text("{}\n", encoding="utf-8")
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root-session",
        cwd=str(tmp_path),
    )
    store.upsert_agent(
        agent_id="external-session",
        agent_handle="external-handle",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="external-session",
        cwd=str(tmp_path),
        session_file=str(session_file),
    )
    stored = store.get_agent("external-session")
    assert stored is not None
    assert stored["session_file"] == str(session_file)
    frame = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="run-answerer",
        agent_id="answerer-agent",
        spec=DispatchSpec(
            argv=["pi", "--mode", "json", "-p"],
            env={"HOME": str(tmp_path / "spoofed-home")},
            cwd=str(tmp_path),
            resume_path=None,
            fork_from="external-handle",
            task="question?",
        ),
    )

    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id="root",
        store=store,
    )

    assert isinstance(dispatch, PreparedDispatch)
    assert dispatch.fork_source_path == str(session_file.resolve())
    assert store.get_run("run-answerer") is not None


@pytest.mark.parametrize(
    "session_file",
    [
        "relative-session.jsonl",
        "external-session-link.jsonl",
    ],
)
@pytest.mark.asyncio
async def test_prepare_dispatch_rejects_unusable_registered_external_session_file(
    tmp_path: Path,
    session_file: str,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    target = tmp_path / "external-session.jsonl"
    target.write_text("{}\n", encoding="utf-8")
    symlink = tmp_path / "external-session-link.jsonl"
    symlink.symlink_to(target)
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root-session",
        cwd=str(tmp_path),
    )
    store.upsert_agent(
        agent_id="external-session",
        agent_handle="external-handle",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="external-session",
        cwd=str(tmp_path),
        session_file=str(tmp_path / session_file) if session_file == symlink.name else session_file,
    )
    frame = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="run-answerer",
        agent_id="answerer-agent",
        spec=DispatchSpec(
            argv=["pi", "--mode", "json", "-p"],
            env={"HOME": str(tmp_path / "spoofed-home")},
            cwd=str(tmp_path),
            resume_path=None,
            fork_from="external-handle",
            task="question?",
        ),
    )

    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id="root",
        store=store,
    )

    assert dispatch == DispatchRejection(reason="fork_target_unknown")
    assert store.get_run("run-answerer") is None


@pytest.mark.asyncio
async def test_prepare_dispatch_allows_fork_from_known_public_handle_across_unrelated_roots(
    tmp_path: Path,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    home = tmp_path / "home"
    session_file = _write_agent_session_file(home, "outside-agent")
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root-session",
        cwd=str(tmp_path),
    )
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="outside-root-session",
        cwd=str(tmp_path),
    )
    store.upsert_agent(
        agent_id="outside-agent",
        agent_handle="outside-handle",
        parent_id="outside-root",
        sibling_group="outside-root",
        depth=1,
        role="agent",
        session_name="outside-agent",
        cwd=str(tmp_path),
    )
    frame = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="run-answerer",
        agent_id="answerer-agent",
        spec=DispatchSpec(
            argv=["pi", "--mode", "json", "-p"],
            env={"HOME": str(home)},
            cwd=str(tmp_path),
            resume_path=None,
            fork_from="outside-handle",
            task="question?",
        ),
    )

    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id="root",
        store=store,
    )

    assert isinstance(dispatch, PreparedDispatch)
    assert dispatch.fork_source_path == str(session_file.resolve())


@pytest.mark.asyncio
async def test_prepare_dispatch_rejects_fork_from_private_id_across_unrelated_roots(
    tmp_path: Path,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    home = tmp_path / "home"
    _write_agent_session_file(home, "outside-agent")
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root-session",
        cwd=str(tmp_path),
    )
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="outside-root-session",
        cwd=str(tmp_path),
    )
    store.upsert_agent(
        agent_id="outside-agent",
        agent_handle="outside-handle",
        parent_id="outside-root",
        sibling_group="outside-root",
        depth=1,
        role="agent",
        session_name="outside-agent",
        cwd=str(tmp_path),
    )
    frame = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="run-answerer",
        agent_id="answerer-agent",
        spec=DispatchSpec(
            argv=["pi", "--mode", "json", "-p"],
            env={"HOME": str(home)},
            cwd=str(tmp_path),
            resume_path=None,
            fork_from="outside-agent",
            task="question?",
        ),
    )

    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id="root",
        store=store,
    )

    assert dispatch == DispatchRejection(reason="fork_target_unknown")
    assert store.get_run("run-answerer") is None


@pytest.mark.asyncio
async def test_prepare_dispatch_rejects_unknown_fork_from_target(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    home = tmp_path / "home"
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd=str(tmp_path),
    )
    frame = DispatchFrame(
        type="dispatch",
        v=PROTOCOL_VERSION,
        run_id="run-answerer",
        agent_id="answerer-agent",
        spec=DispatchSpec(
            argv=["pi", "--mode", "json", "-p"],
            env={"HOME": str(home)},
            cwd=str(tmp_path),
            resume_path=None,
            fork_from="missing-target",
            task="question?",
        ),
    )

    dispatch = await prepare_dispatch(
        frame=frame,
        dispatcher_node_id="root",
        store=store,
    )

    assert dispatch == DispatchRejection(reason="fork_target_unknown")
    assert store.get_run("run-answerer") is None
