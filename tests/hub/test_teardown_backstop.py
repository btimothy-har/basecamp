"""Teardown/backstop hardening tests for issue #310.

Covers the reconcile terminal-row sweep, v27 force-gating, unverified-liveness
skip, exception isolation, and the branch_base=None guard — complementing the
teardown decision tests in ``test_dispatch_reaper.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from basecamp.hub.store import Store
from basecamp.hub.swarm.process import (
    reconcile_orphaned_runs,
    teardown_agent_workspace,
)


def _create_terminal_run(
    store: Store,
    *,
    run_id: str,
    agent_id: str,
    spec: dict[str, object],
    status: str = "completed",
) -> None:
    store.create_run(run_id=run_id, agent_id=agent_id, dispatcher_id="root", spec=spec)
    store.set_run_result(run_id=run_id, status=status, result="done", error=None)


def test_reconcile_reclaims_terminal_row_with_surviving_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    teardowns: list[str] = []
    monkeypatch.setattr("basecamp.hub.swarm.process.os.path.exists", lambda p: p == "/wt/surviving")
    monkeypatch.setattr(
        "basecamp.hub.swarm.process.teardown_agent_workspace",
        lambda wt, **_kw: teardowns.append(wt),
    )
    _create_terminal_run(
        store,
        run_id="run-surviving",
        agent_id="agent-surviving",
        spec={"owned_worktree": "/wt/surviving", "owned_branch": "agent/surv", "branch_created": True},
    )

    reconcile_orphaned_runs(store)

    assert teardowns == ["/wt/surviving"]


def test_reconcile_skips_terminal_row_whose_worktree_is_gone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    teardowns: list[str] = []
    monkeypatch.setattr("basecamp.hub.swarm.process.os.path.exists", lambda _p: False)
    monkeypatch.setattr(
        "basecamp.hub.swarm.process.teardown_agent_workspace",
        lambda wt, **_kw: teardowns.append(wt),
    )
    _create_terminal_run(
        store,
        run_id="run-gone",
        agent_id="agent-gone",
        spec={"owned_worktree": "/wt/gone", "owned_branch": "agent/gone", "branch_created": True},
    )

    reconcile_orphaned_runs(store)

    assert teardowns == []


def test_reconcile_terminal_sweep_does_not_refinalize_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    monkeypatch.setattr("basecamp.hub.swarm.process.os.path.exists", lambda _p: True)
    monkeypatch.setattr("basecamp.hub.swarm.process.teardown_agent_workspace", lambda _wt, **_kw: None)
    _create_terminal_run(
        store,
        run_id="run-completed",
        agent_id="agent-completed",
        spec={"owned_worktree": "/wt/completed", "owned_branch": "agent/c", "branch_created": True},
        status="completed",
    )

    reconcile_orphaned_runs(store)

    run = store.get_run("run-completed")
    assert run is not None
    assert run["status"] == "completed"
    assert run["result"] == "done"


def test_teardown_pre_upgrade_spec_uses_non_force_removal(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(args)
        if "rev-parse" in args:
            return SimpleNamespace(returncode=0, stdout="/home/u/repo/.git\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("basecamp.hub.swarm.process.subprocess.run", fake_run)

    teardown_agent_workspace("/wt/legacy", force=False)

    remove_calls = [c for c in calls if "remove" in c]
    assert remove_calls
    assert "--force" not in remove_calls[0]


def test_teardown_v27_spec_with_null_branch_uses_force_and_no_branch_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(args)
        if "rev-parse" in args:
            return SimpleNamespace(returncode=0, stdout="/home/u/repo/.git\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("basecamp.hub.swarm.process.subprocess.run", fake_run)

    teardown_agent_workspace("/wt/report", branch=None, branch_created=False, force=True)

    remove_calls = [c for c in calls if "remove" in c]
    assert remove_calls
    assert "--force" in remove_calls[0]
    assert not any("branch" in c and "-D" in c for c in calls)
    assert not any("rev-list" in c for c in calls)


def test_reconcile_skips_unverified_liveness_row_but_processes_remaining(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    teardowns: list[str] = []

    # First row: unverified liveness (ps probe fails). Second row: no pgid at all
    # so liveness is trivially unverified via the None path — but we want one row
    # that *is* verified and gets torn down. Use three rows: unverified, verified, no-pgid.
    monkeypatch.setattr("basecamp.hub.swarm.process._process_group_is_runner", lambda pgid: pgid == 999)
    monkeypatch.setattr(
        "basecamp.hub.swarm.process.teardown_agent_workspace",
        lambda wt, **_kw: teardowns.append(wt),
    )
    store.create_run(
        run_id="run-unverified",
        agent_id="agent-unverified",
        dispatcher_id="root",
        spec={"owned_worktree": "/wt/unverified", "owned_branch": "agent/u", "branch_created": True},
    )
    store.set_run_pgid(run_id="run-unverified", pgid=777)
    store.create_run(
        run_id="run-verified",
        agent_id="agent-verified",
        dispatcher_id="root",
        spec={"owned_worktree": "/wt/verified", "owned_branch": "agent/v", "branch_created": True},
    )
    store.set_run_pgid(run_id="run-verified", pgid=999)

    reconcile_orphaned_runs(store)

    assert "/wt/unverified" not in teardowns
    assert "/wt/verified" in teardowns


def test_teardown_timeout_expired_does_not_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(_args: list[str], **_kwargs: object) -> SimpleNamespace:
        raise subprocess.TimeoutExpired(cmd="git", timeout=15)

    monkeypatch.setattr("basecamp.hub.swarm.process.subprocess.run", fake_run)

    teardown_agent_workspace("/wt/slow", branch="agent/slow", branch_base="abc", branch_created=True)


def test_reconcile_one_row_failure_does_not_abort_remaining_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    teardowns: list[str] = []
    call_count = 0

    def flaky_teardown(wt: str, **_kw: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("boom")
        teardowns.append(wt)

    monkeypatch.setattr("basecamp.hub.swarm.process._process_group_is_runner", lambda _pgid: True)
    monkeypatch.setattr("basecamp.hub.swarm.process.terminate_process_group", lambda _pgid, **_kw: None)
    monkeypatch.setattr("basecamp.hub.swarm.process.teardown_agent_workspace", flaky_teardown)
    store.create_run(
        run_id="run-explodes",
        agent_id="agent-explodes",
        dispatcher_id="root",
        spec={"owned_worktree": "/wt/explodes", "owned_branch": "agent/e", "branch_created": True},
    )
    store.set_run_pgid(run_id="run-explodes", pgid=1111)
    store.create_run(
        run_id="run-survives",
        agent_id="agent-survives",
        dispatcher_id="root",
        spec={"owned_worktree": "/wt/survives", "owned_branch": "agent/s", "branch_created": True},
    )
    store.set_run_pgid(run_id="run-survives", pgid=2222)

    reconcile_orphaned_runs(store)

    assert "/wt/survives" in teardowns
    assert store.get_run("run-survives")["status"] == "failed"


def test_teardown_branch_base_none_keeps_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(args)
        if "rev-parse" in args:
            return SimpleNamespace(returncode=0, stdout="/home/u/repo/.git\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("basecamp.hub.swarm.process.subprocess.run", fake_run)

    teardown_agent_workspace(
        "/wt/agent/worker",
        branch="agent/worker",
        branch_base=None,
        branch_created=True,
    )

    assert not any("rev-list" in c for c in calls)
    assert not any("branch" in c and "-D" in c for c in calls)


def test_reconcile_terminal_sweep_one_row_failure_does_not_abort_remaining(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    teardowns: list[str] = []
    call_count = 0

    def flaky_teardown(wt: str, **_kw: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("boom")
        teardowns.append(wt)

    monkeypatch.setattr("basecamp.hub.swarm.process.os.path.exists", lambda _p: True)
    monkeypatch.setattr("basecamp.hub.swarm.process.teardown_agent_workspace", flaky_teardown)
    _create_terminal_run(
        store,
        run_id="run-explodes",
        agent_id="agent-explodes",
        spec={"owned_worktree": "/wt/explodes", "owned_branch": "agent/e", "branch_created": True},
    )
    _create_terminal_run(
        store,
        run_id="run-survives",
        agent_id="agent-survives",
        spec={"owned_worktree": "/wt/survives", "owned_branch": "agent/s", "branch_created": True},
    )

    reconcile_orphaned_runs(store)

    assert "/wt/survives" in teardowns


def test_reconcile_nonterminal_no_pgid_skips_teardown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A nonterminal row with no pgid has unverified liveness: teardown must be
    # skipped (left for the next reconcile) rather than force-removing a possibly-live tree.
    store = Store(db_path=tmp_path / "daemon.db")
    teardowns: list[str] = []
    monkeypatch.setattr(
        "basecamp.hub.swarm.process.teardown_agent_workspace",
        lambda wt, **_kw: teardowns.append(wt),
    )
    store.create_run(
        run_id="run-no-pgid",
        agent_id="agent-no-pgid",
        dispatcher_id="root",
        spec={"owned_worktree": "/wt/no-pgid", "owned_branch": "agent/n", "branch_created": True},
    )

    reconcile_orphaned_runs(store)

    assert teardowns == []
    run = store.get_run("run-no-pgid")
    assert run is not None
    assert run["status"] == "failed"
