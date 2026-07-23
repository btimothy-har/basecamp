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
    wt = tmp_path / "wt-surviving"
    wt.mkdir()

    monkeypatch.setattr("basecamp.hub.swarm.process._process_group_verified_dead", lambda _pgid: True)
    monkeypatch.setattr(
        "basecamp.hub.swarm.process.teardown_agent_workspace",
        lambda worktree, **_kw: teardowns.append(worktree),
    )
    store.create_run(
        run_id="run-surviving",
        agent_id="agent-surviving",
        dispatcher_id="root",
        spec={"owned_worktree": str(wt), "owned_branch": "agent/surv", "branch_created": True},
    )
    store.set_run_pgid(run_id="run-surviving", pgid=888)
    store.set_run_result(run_id="run-surviving", status="completed", result="done", error=None)

    reconcile_orphaned_runs(store)

    assert teardowns == [str(wt)]


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

    wt_unverified = tmp_path / "wt-unverified"
    wt_unverified.mkdir()
    wt_verified = tmp_path / "wt-verified"
    wt_verified.mkdir()

    # pgid 999 is a live runner that gets terminated and is then provably dead; pgid 777 is
    # not a runner and its liveness is unverifiable (ps probe shows a live, non-runner process).
    monkeypatch.setattr("basecamp.hub.swarm.process._process_group_is_runner", lambda pgid: pgid == 999)
    monkeypatch.setattr("basecamp.hub.swarm.process.terminate_process_group", lambda _pgid, **_kw: None)
    # Teardown is gated on provable death for BOTH rows: pgid 999 is verified dead (torn down),
    # pgid 777 is not (deferred). Terminating a runner is never on its own sufficient — the tree
    # is only reclaimed once the group is confirmed gone.
    monkeypatch.setattr(
        "basecamp.hub.swarm.process._process_group_verified_dead",
        lambda pgid: pgid != 777,
    )
    monkeypatch.setattr(
        "basecamp.hub.swarm.process.teardown_agent_workspace",
        lambda worktree, **_kw: teardowns.append(worktree),
    )
    store.create_run(
        run_id="run-unverified",
        agent_id="agent-unverified",
        dispatcher_id="root",
        spec={"owned_worktree": str(wt_unverified), "owned_branch": "agent/u", "branch_created": True},
    )
    store.set_run_pgid(run_id="run-unverified", pgid=777)
    store.create_run(
        run_id="run-verified",
        agent_id="agent-verified",
        dispatcher_id="root",
        spec={"owned_worktree": str(wt_verified), "owned_branch": "agent/v", "branch_created": True},
    )
    store.set_run_pgid(run_id="run-verified", pgid=999)

    reconcile_orphaned_runs(store)

    # The unverified row's worktree exists on disk but must NOT be torn down —
    # neither the nonterminal pass (unverifiable) nor the terminal sweep (pgid
    # not provably dead) may touch it. The verified row IS torn down.
    assert str(wt_unverified) not in teardowns
    assert str(wt_verified) in teardowns


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

    monkeypatch.setattr("basecamp.hub.swarm.process._process_group_verified_dead", lambda _pgid: True)
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
    # The worktree exists on disk so the terminal sweep's os.path.exists check does NOT
    # accidentally filter it — the liveness gate is what protects it.
    store = Store(db_path=tmp_path / "daemon.db")
    teardowns: list[str] = []
    wt = tmp_path / "wt-no-pgid"
    wt.mkdir()

    monkeypatch.setattr(
        "basecamp.hub.swarm.process.teardown_agent_workspace",
        lambda worktree, **_kw: teardowns.append(worktree),
    )
    store.create_run(
        run_id="run-no-pgid",
        agent_id="agent-no-pgid",
        dispatcher_id="root",
        spec={"owned_worktree": str(wt), "owned_branch": "agent/n", "branch_created": True},
    )

    reconcile_orphaned_runs(store)

    assert teardowns == []
    run = store.get_run("run-no-pgid")
    assert run is not None
    assert run["status"] == "failed"


def test_reconcile_terminated_runner_not_yet_dead_is_deferred(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A live runner is terminated, but SIGKILL may not have landed yet (e.g. uninterruptible
    # I/O). Terminating is NOT sufficient to reclaim the tree: teardown must be deferred until
    # the group is provably dead, so a still-dying runner never has its workspace force-removed.
    store = Store(db_path=tmp_path / "daemon.db")
    teardowns: list[str] = []
    wt = tmp_path / "wt-dying"
    wt.mkdir()

    monkeypatch.setattr("basecamp.hub.swarm.process._process_group_is_runner", lambda _pgid: True)
    monkeypatch.setattr("basecamp.hub.swarm.process.terminate_process_group", lambda _pgid, **_kw: None)
    # Still alive after termination (SIGKILL queued behind D-state I/O).
    monkeypatch.setattr("basecamp.hub.swarm.process._process_group_verified_dead", lambda _pgid: False)
    monkeypatch.setattr(
        "basecamp.hub.swarm.process.teardown_agent_workspace",
        lambda worktree, **_kw: teardowns.append(worktree),
    )
    store.create_run(
        run_id="run-dying",
        agent_id="agent-dying",
        dispatcher_id="root",
        spec={"owned_worktree": str(wt), "owned_branch": "agent/d", "branch_created": True},
    )
    store.set_run_pgid(run_id="run-dying", pgid=888)

    reconcile_orphaned_runs(store)

    assert teardowns == [], "a terminated-but-not-yet-dead runner's tree is never force-removed"


def test_reconcile_terminal_sweep_tears_down_verified_dead_pgid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A terminal row with a provably-dead pgid and a surviving real worktree IS
    # torn down by the terminal sweep — the liveness gate passes.
    store = Store(db_path=tmp_path / "daemon.db")
    teardowns: list[str] = []
    wt = tmp_path / "wt-dead"
    wt.mkdir()

    monkeypatch.setattr(
        "basecamp.hub.swarm.process._process_group_verified_dead",
        lambda pgid: pgid == 555,
    )
    monkeypatch.setattr(
        "basecamp.hub.swarm.process.teardown_agent_workspace",
        lambda worktree, **_kw: teardowns.append(worktree),
    )
    store.create_run(
        run_id="run-dead",
        agent_id="agent-dead",
        dispatcher_id="root",
        spec={"owned_worktree": str(wt), "owned_branch": "agent/dead", "branch_created": True},
    )
    store.set_run_pgid(run_id="run-dead", pgid=555)
    store.set_run_result(run_id="run-dead", status="completed", result="done", error=None)

    reconcile_orphaned_runs(store)

    assert teardowns == [str(wt)]


def test_reconcile_terminal_sweep_skips_null_pgid_with_surviving_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A terminal row with pgid None and a surviving real worktree is skipped —
    # the liveness gate cannot verify a null pgid, so the worktree is left for
    # the session-start sweep rather than force-removed.
    store = Store(db_path=tmp_path / "daemon.db")
    teardowns: list[str] = []
    wt = tmp_path / "wt-null-pgid"
    wt.mkdir()

    monkeypatch.setattr(
        "basecamp.hub.swarm.process.teardown_agent_workspace",
        lambda worktree, **_kw: teardowns.append(worktree),
    )
    _create_terminal_run(
        store,
        run_id="run-null",
        agent_id="agent-null",
        spec={"owned_worktree": str(wt), "owned_branch": "agent/null", "branch_created": True},
    )

    reconcile_orphaned_runs(store)

    assert teardowns == []
