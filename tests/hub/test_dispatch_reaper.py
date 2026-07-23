"""Disconnect-reaper and orphaned-run reconciliation tests."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from dispatch_helpers import _FakePidProcess

from basecamp.hub.registry import Registry, Waiter
from basecamp.hub.store import Store
from basecamp.hub.swarm.process import reconcile_orphaned_runs, teardown_agent_workspace
from basecamp.hub.swarm.run_result import (
    FinalRunResult,
    RunResultSidecar,
    run_result_path,
    write_run_result,
)
from basecamp.hub.swarm.service.reaper import (
    DEFAULT_DISCONNECT_GRACE_SECONDS,
    _resolve_disconnect_grace_s,
    _run_disconnect_reaper,
    schedule_disconnect_reaper,
)

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

    monkeypatch.setattr("basecamp.hub.swarm.service.reaper.terminate_process_group_if_runner", record_terminate)
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
        "basecamp.hub.swarm.service.reaper.terminate_process_group_if_runner",
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
        "basecamp.hub.swarm.service.reaper.terminate_process_group_if_runner",
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
        "basecamp.hub.swarm.service.reaper.terminate_process_group_if_runner",
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

    monkeypatch.setattr("basecamp.hub.swarm.service.reaper.terminate_process_group_if_runner", record_terminate)
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
    monkeypatch.setattr("basecamp.hub.swarm.process._process_group_is_runner", lambda _pgid: False)

    reconcile_orphaned_runs(store)

    for run_id in ["run-running", "run-pending"]:
        run = store.get_run(run_id)
        assert run is not None
        assert run["status"] == "failed"
        assert run["result"] is None
        assert run["error"] == "daemon_restart_reconciled"


def test_reconcile_orphaned_runs_recovers_completed_from_sidecar_final(tmp_path: Path) -> None:
    # Regression for #260 review: a runner writes its sidecar `final` before it
    # exits, so a run left nonterminal by a daemon crash may already hold a
    # completed result on disk. Restart reconciliation — the only finalizer left
    # for that run — must honor it rather than clobber it with daemon_restart.
    store = Store(db_path=tmp_path / "daemon.db")
    run_id = "run-recovered"
    agent_id = "agent-recovered"
    store.create_run(run_id=run_id, agent_id=agent_id, dispatcher_id="root", spec={})
    write_run_result(
        run_result_path(agent_id, run_id),
        RunResultSidecar(
            run_id=run_id,
            agent_id=agent_id,
            attempts=[],
            final=FinalRunResult(status="ok", result="recovered-result", error=None, retry_count=0),
        ),
    )

    reconcile_orphaned_runs(store)

    run = store.get_run(run_id)
    assert run is not None
    assert run["status"] == "completed"
    assert run["result"] == "recovered-result"
    assert run["error"] is None


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

    monkeypatch.setattr("basecamp.hub.swarm.process.terminate_process_group_if_runner", record_terminate)

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

    monkeypatch.setattr("basecamp.hub.swarm.process._process_group_is_runner", lambda _pgid: False)
    monkeypatch.setattr("basecamp.hub.swarm.process.terminate_process_group", record_terminate)

    reconcile_orphaned_runs(store)

    assert calls == []
    run = store.get_run("run-mismatch")
    assert run is not None
    assert run["status"] == "failed"
    assert run["error"] == "daemon_restart_reconciled"


def test_teardown_force_removes_worktree_from_main_root(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(args)
        if "rev-parse" in args:
            return SimpleNamespace(returncode=0, stdout="/home/u/repo/.git\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("basecamp.hub.swarm.process.subprocess.run", fake_run)

    teardown_agent_workspace("/wt/agent-abc/worker")

    assert ["git", "-C", "/wt/agent-abc/worker", "rev-parse", "--path-format=absolute", "--git-common-dir"] in calls
    assert ["git", "-C", "/home/u/repo", "worktree", "unlock", "/wt/agent-abc/worker"] in calls
    # --force: dirty state is discarded by design; commits are the only durable output.
    assert ["git", "-C", "/home/u/repo", "worktree", "remove", "--force", "/wt/agent-abc/worker"] in calls
    assert not any("branch" in call and "-D" in call for call in calls)


@pytest.mark.parametrize(
    ("branch_created", "rev_list_count", "rev_list_fail", "expect_delete"),
    [
        (True, 0, False, True),
        (True, 3, False, False),
        (False, 0, False, False),
        (True, 0, True, False),
    ],
)
def test_teardown_branch_deletion_decision(
    monkeypatch: pytest.MonkeyPatch,
    *,
    branch_created: bool,
    rev_list_count: int,
    rev_list_fail: bool,
    expect_delete: bool,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(args)
        if "rev-parse" in args:
            return SimpleNamespace(returncode=0, stdout="/home/u/repo/.git\n", stderr="")
        if "rev-list" in args:
            if rev_list_fail:
                return SimpleNamespace(returncode=1, stdout="", stderr="bad ref")
            return SimpleNamespace(returncode=0, stdout=f"{rev_list_count}\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("basecamp.hub.swarm.process.subprocess.run", fake_run)

    teardown_agent_workspace(
        "/wt/agent/worker",
        branch="agent/worker",
        branch_base="abc123",
        branch_created=branch_created,
    )

    remove_calls = [c for c in calls if "remove" in c]
    assert remove_calls and "--force" in remove_calls[0]

    branch_delete_calls = [c for c in calls if "branch" in c and "-D" in c]
    assert bool(branch_delete_calls) == expect_delete

    rev_list_calls = [c for c in calls if "rev-list" in c]
    assert bool(rev_list_calls) == branch_created

    if expect_delete:
        # git refuses to delete a checked-out branch, so deletion must follow worktree removal.
        assert calls.index(branch_delete_calls[0]) > calls.index(remove_calls[0])


def test_teardown_skips_when_common_dir_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(args)
        return SimpleNamespace(returncode=1, stdout="", stderr="not a git repository")

    monkeypatch.setattr("basecamp.hub.swarm.process.subprocess.run", fake_run)

    teardown_agent_workspace("/gone", branch="agent/worker", branch_base="abc", branch_created=True)

    assert all("remove" not in args for args in calls)
    assert all("branch" not in args for args in calls)


def test_reconcile_orphaned_runs_teardown_with_branch_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A run orphaned by a daemon crash never fired its reaper, so reconciliation must tear down
    # its workspace — the sweep can't (the crash-interrupted branch is not merged yet).
    store = Store(db_path=tmp_path / "daemon.db")
    teardowns: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr("basecamp.hub.swarm.process._process_group_is_runner", lambda _pgid: True)
    monkeypatch.setattr("basecamp.hub.swarm.process.terminate_process_group", lambda _pgid, **_kw: None)
    monkeypatch.setattr(
        "basecamp.hub.swarm.process.teardown_agent_workspace",
        lambda wt, **kw: teardowns.append((wt, kw)),
    )
    store.create_run(
        run_id="run-owns-wt",
        agent_id="agent-owns-wt",
        dispatcher_id="root",
        spec={
            "owned_worktree": "/wt/agent-xyz/worker",
            "owned_branch": "agent/xyz",
            "branch_base": "abc123",
            "branch_created": True,
        },
    )
    store.set_run_pgid(run_id="run-owns-wt", pgid=4321)

    reconcile_orphaned_runs(store)

    assert teardowns == [
        (
            "/wt/agent-xyz/worker",
            {"branch": "agent/xyz", "branch_base": "abc123", "branch_created": True, "force": True},
        ),
    ]


def test_reconcile_orphaned_runs_pre_upgrade_spec_non_force_removes_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pre-upgrade spec_json lacks the branch_created key; reconcile passes force=False to
    # preserve the old contract's dirty-residual behavior during the one-time upgrade window.
    store = Store(db_path=tmp_path / "daemon.db")
    teardowns: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr("basecamp.hub.swarm.process._process_group_is_runner", lambda _pgid: True)
    monkeypatch.setattr("basecamp.hub.swarm.process.terminate_process_group", lambda _pgid, **_kw: None)
    monkeypatch.setattr(
        "basecamp.hub.swarm.process.teardown_agent_workspace",
        lambda wt, **kw: teardowns.append((wt, kw)),
    )
    store.create_run(
        run_id="run-legacy",
        agent_id="agent-legacy",
        dispatcher_id="root",
        spec={"owned_worktree": "/wt/agent/legacy"},
    )
    store.set_run_pgid(run_id="run-legacy", pgid=4322)

    reconcile_orphaned_runs(store)

    assert teardowns == [
        ("/wt/agent/legacy", {"branch": None, "branch_base": None, "branch_created": False, "force": False}),
    ]
