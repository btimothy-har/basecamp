"""Tests for the daemon-side agent-worktree backstop sweep.

Each test creates a real temp git repo and worktrees under a temp WORKTREES_ROOT
(never the real ``~/.worktrees``), then exercises one sweep coverage category.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from basecamp.hub.server import (
    _DEFAULT_SWEEP_INTERVAL_S,
    _resolve_sweep_interval_s,
    create_server,
)
from basecamp.hub.store import Store
from basecamp.hub.swarm.sweep import (
    SweepResult,
    is_agent_branch,
    is_agent_workspace_path,
    run_periodic_sweep,
    sweep_agent_worktrees,
)


def _git(cwd: str, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", cwd, *args],
        capture_output=True,
        text=True,
        check=check,
        timeout=15,
    )


def _make_repo(path: Path) -> str:
    """Create a real git repo with one commit on ``main``."""
    path.mkdir(parents=True, exist_ok=True)
    _git(str(path), ["init", "-b", "main"])
    _git(str(path), ["config", "user.email", "test@example.com"])
    _git(str(path), ["config", "user.name", "Test"])
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(str(path), ["add", "."])
    _git(str(path), ["commit", "-m", "initial"])
    return str(path)


def _add_worktree(
    main: str,
    wt_path: str,
    *,
    branch: str | None = None,
    detach: bool = False,
) -> None:
    """Add a git worktree at *wt_path*, optionally creating a new branch."""
    wt_path_obj = Path(wt_path)
    wt_path_obj.parent.mkdir(parents=True, exist_ok=True)
    args: list[str] = ["worktree", "add"]
    if detach:
        args.append("--detach")
    elif branch is not None:
        args.extend(["-b", branch])
    args.append(wt_path)
    if not detach and branch is None:
        args.append("main")
    _git(main, args)


def _lock_worktree(main: str, wt_path: str, reason: str) -> None:
    _git(main, ["worktree", "lock", "--reason", reason, wt_path])


def _merge_branch(main: str, branch: str) -> None:
    """Merge *branch* into main so the agent branch becomes integrated."""
    _git(main, ["merge", "--no-ff", branch, "-m", f"merge {branch}"])


def _iso_timestamp(delta_seconds: float = 0) -> str:
    ts = datetime.now(UTC) + timedelta(seconds=delta_seconds)
    return ts.isoformat()


def _make_repo_and_root(tmp_path: Path) -> tuple[str, str]:
    """Create a main checkout and a WORKTREES_ROOT under tmp_path."""
    main = _make_repo(tmp_path / "main")
    root = str(tmp_path / "worktrees")
    os.makedirs(root, exist_ok=True)
    return main, root


def _wt_path(root: str, identity: str, label: str) -> str:
    return os.path.join(root, identity, label)


# --------------------------------------------------------------------------- category 1


def test_integrated_agent_worktree_removed_and_branch_deleted(tmp_path: Path) -> None:
    main, root = _make_repo_and_root(tmp_path)
    agent_wt = _wt_path(root, "org/repo", "agent-abc1/worker")
    _add_worktree(main, agent_wt, branch="agent/abc1")
    _merge_branch(main, "agent/abc1")

    result = sweep_agent_worktrees(worktrees_root=root)

    assert agent_wt in result.removed
    assert not Path(agent_wt).exists()
    branches = _git(main, ["branch", "--format=%(refname:short)"]).stdout.split()
    assert "agent/abc1" not in branches


def test_legacy_agent_branch_worktree_removed(tmp_path: Path) -> None:
    main, root = _make_repo_and_root(tmp_path)
    agent_wt = _wt_path(root, "org/repo", "agent-xyz2/worker")
    _add_worktree(main, agent_wt, branch="agent-xyz2/worker")
    _merge_branch(main, "agent-xyz2/worker")

    result = sweep_agent_worktrees(worktrees_root=root)

    assert agent_wt in result.removed
    assert not Path(agent_wt).exists()


# --------------------------------------------------------------------------- category 2


def test_detached_agent_residue_removed(tmp_path: Path) -> None:
    main, root = _make_repo_and_root(tmp_path)
    agent_wt = _wt_path(root, "org/repo", "agent-det1/report")
    _add_worktree(main, agent_wt, detach=True)

    result = sweep_agent_worktrees(worktrees_root=root)

    assert agent_wt in result.removed
    assert not Path(agent_wt).exists()


def test_detached_non_agent_path_not_removed(tmp_path: Path) -> None:
    main, root = _make_repo_and_root(tmp_path)
    # A session worktree with a direct label — not agent residue.
    session_wt = _wt_path(root, "org/repo", "my-feature")
    _add_worktree(main, session_wt, branch="session/my-feature")

    result = sweep_agent_worktrees(worktrees_root=root)

    assert session_wt not in result.removed
    assert Path(session_wt).exists()


# --------------------------------------------------------------------------- category 3


def test_stale_locked_agent_worktree_removed(tmp_path: Path) -> None:
    main, root = _make_repo_and_root(tmp_path)
    agent_wt = _wt_path(root, "org/repo", "agent-old1/worker")
    _add_worktree(main, agent_wt, branch="agent/old1")
    _merge_branch(main, "agent/old1")
    # Lock with a timestamp 25h ago — past the 24h staleness threshold.
    stale_ts = _iso_timestamp(delta_seconds=-(25 * 3600))
    _lock_worktree(main, agent_wt, f"basecamp agent run {stale_ts}")

    result = sweep_agent_worktrees(worktrees_root=root)

    assert agent_wt in result.removed
    assert not Path(agent_wt).exists()


def test_fresh_locked_agent_worktree_skipped(tmp_path: Path) -> None:
    main, root = _make_repo_and_root(tmp_path)
    agent_wt = _wt_path(root, "org/repo", "agent-fresh/worker")
    _add_worktree(main, agent_wt, branch="agent/fresh")
    _merge_branch(main, "agent/fresh")
    # Lock with a timestamp 1h ago — well within the 24h freshness window.
    fresh_ts = _iso_timestamp(delta_seconds=-3600)
    _lock_worktree(main, agent_wt, f"basecamp agent run {fresh_ts}")

    result = sweep_agent_worktrees(worktrees_root=root)

    assert agent_wt not in result.removed
    assert Path(agent_wt).exists()


def test_stale_locked_detached_worktree_removed(tmp_path: Path) -> None:
    main, root = _make_repo_and_root(tmp_path)
    agent_wt = _wt_path(root, "org/repo", "agent-stale2/report")
    _add_worktree(main, agent_wt, detach=True)
    stale_ts = _iso_timestamp(delta_seconds=-(25 * 3600))
    _lock_worktree(main, agent_wt, f"basecamp agent run {stale_ts}")

    result = sweep_agent_worktrees(worktrees_root=root)

    assert agent_wt in result.removed
    assert not Path(agent_wt).exists()


def test_fresh_locked_detached_worktree_skipped(tmp_path: Path) -> None:
    main, root = _make_repo_and_root(tmp_path)
    agent_wt = _wt_path(root, "org/repo", "agent-fresh2/report")
    _add_worktree(main, agent_wt, detach=True)
    fresh_ts = _iso_timestamp(delta_seconds=-3600)
    _lock_worktree(main, agent_wt, f"basecamp agent run {fresh_ts}")

    result = sweep_agent_worktrees(worktrees_root=root)

    assert agent_wt not in result.removed
    assert Path(agent_wt).exists()


def test_foreign_locked_agent_worktree_skipped(tmp_path: Path) -> None:
    """A locked agent worktree whose lock reason is foreign (not agent-run) is skipped."""
    main, root = _make_repo_and_root(tmp_path)
    agent_wt = _wt_path(root, "org/repo", "agent-foreign/worker")
    _add_worktree(main, agent_wt, branch="agent/foreign")
    _merge_branch(main, "agent/foreign")
    _lock_worktree(main, agent_wt, "some other reason")

    result = sweep_agent_worktrees(worktrees_root=root)

    assert agent_wt not in result.removed
    assert Path(agent_wt).exists()


# --------------------------------------------------------------------------- category 4


def test_unintegrated_agent_branch_kept(tmp_path: Path) -> None:
    main, root = _make_repo_and_root(tmp_path)
    agent_wt = _wt_path(root, "org/repo", "agent-unint/worker")
    _add_worktree(main, agent_wt, branch="agent/unint")
    # Add a commit on the agent branch so it is NOT an ancestor of main.
    (Path(agent_wt) / "change.txt").write_text("uncommitted work\n", encoding="utf-8")
    _git(agent_wt, ["add", "."])
    _git(agent_wt, ["commit", "-m", "agent work"])

    result = sweep_agent_worktrees(worktrees_root=root)

    assert agent_wt not in result.removed
    assert Path(agent_wt).exists()
    branches = _git(main, ["branch", "--format=%(refname:short)"]).stdout.split()
    assert "agent/unint" in branches


def test_orphan_integrated_branch_deleted(tmp_path: Path) -> None:
    main, root = _make_repo_and_root(tmp_path)
    # Create an agent branch + worktree, merge it, then manually remove the worktree
    # (simulating the worktree already being gone but the orphan branch remaining).
    agent_wt = _wt_path(root, "org/repo", "agent-orphan/worker")
    _add_worktree(main, agent_wt, branch="agent/orphan")
    _merge_branch(main, "agent/orphan")
    _git(main, ["worktree", "remove", "--force", agent_wt])
    assert not Path(agent_wt).exists()
    # The branch still exists as an orphan.
    branches_before = _git(main, ["branch", "--format=%(refname:short)"]).stdout.split()
    assert "agent/orphan" in branches_before

    # But the sweep discovers main checkouts by walking WORKTREES_ROOT. With the only
    # worktree gone, there's nothing to discover. Create a session worktree so the main
    # checkout is discoverable.
    session_wt = _wt_path(root, "org/repo", "dev-session")
    _add_worktree(main, session_wt, branch="session/dev")

    result = sweep_agent_worktrees(worktrees_root=root)

    branches_after = _git(main, ["branch", "--format=%(refname:short)"]).stdout.split()
    assert "agent/orphan" not in branches_after
    assert "dev-session" not in result.removed


def test_orphan_unintegrated_branch_kept(tmp_path: Path) -> None:
    main, root = _make_repo_and_root(tmp_path)
    agent_wt = _wt_path(root, "org/repo", "agent-keep/worker")
    _add_worktree(main, agent_wt, branch="agent/keep")
    # Add a commit so the branch is NOT an ancestor of main (unintegrated).
    (Path(agent_wt) / "change.txt").write_text("durable work\n", encoding="utf-8")
    _git(agent_wt, ["add", "."])
    _git(agent_wt, ["commit", "-m", "keep this"])
    _git(main, ["worktree", "remove", "--force", agent_wt])
    # A session worktree so the main checkout is discoverable.
    session_wt = _wt_path(root, "org/repo", "dev")
    _add_worktree(main, session_wt, branch="session/dev")

    sweep_agent_worktrees(worktrees_root=root)

    branches = _git(main, ["branch", "--format=%(refname:short)"]).stdout.split()
    assert "agent/keep" in branches


# --------------------------------------------------------------------------- session worktrees


def test_session_worktrees_ignored(tmp_path: Path) -> None:
    main, root = _make_repo_and_root(tmp_path)
    wt_session = _wt_path(root, "org/repo", "wt-ab/myfeature")
    copilot_wt = _wt_path(root, "org/repo", "copilot/task")
    direct_wt = _wt_path(root, "org/repo", "direct-label")

    for i, wt in enumerate([wt_session, copilot_wt, direct_wt]):
        _add_worktree(main, wt, branch=f"session/wt{i}")

    result = sweep_agent_worktrees(worktrees_root=root)

    for wt in [wt_session, copilot_wt, direct_wt]:
        assert wt not in result.removed
        assert Path(wt).exists()


def test_session_worktree_branch_not_deleted(tmp_path: Path) -> None:
    main, root = _make_repo_and_root(tmp_path)
    # A session worktree on a wt/ branch — the sweep must not touch it even if
    # the branch looks like it could be "integrated" into main.
    wt_session = _wt_path(root, "org/repo", "wt-ab/feature")
    _add_worktree(main, wt_session, branch="wt/feature")
    _merge_branch(main, "wt/feature")

    result = sweep_agent_worktrees(worktrees_root=root)

    assert wt_session not in result.removed
    assert Path(wt_session).exists()
    branches = _git(main, ["branch", "--format=%(refname:short)"]).stdout.split()
    assert "wt/feature" in branches


# --------------------------------------------------------------------------- error resilience


def test_sweep_does_not_crash_on_missing_root(tmp_path: Path) -> None:
    result = sweep_agent_worktrees(worktrees_root=str(tmp_path / "nonexistent"))
    assert isinstance(result, SweepResult)
    assert result.removed == []


def test_sweep_does_not_crash_on_broken_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A git subprocess failure must not crash the sweep."""
    main, root = _make_repo_and_root(tmp_path)
    agent_wt = _wt_path(root, "org/repo", "agent-broken/worker")
    _add_worktree(main, agent_wt, branch="agent/broken")
    _merge_branch(main, "agent/broken")

    original_run = subprocess.run
    call_count = {"n": 0}

    def flaky_git(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        call_count["n"] += 1
        # Let the discovery (rev-parse) succeed but make worktree list fail.
        if "worktree" in args and "list" in args:
            raise subprocess.SubprocessError
        return original_run(args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("basecamp.hub.swarm.sweep.subprocess.run", flaky_git)
    result = sweep_agent_worktrees(worktrees_root=root)

    assert isinstance(result, SweepResult)


# --------------------------------------------------------------------------- unit helpers


def test_is_agent_branch_recognizes_namespaces() -> None:
    assert is_agent_branch("agent/handle")
    assert is_agent_branch("agent-abc123/worker")
    assert not is_agent_branch("main")
    assert not is_agent_branch("wt/feature")
    assert not is_agent_branch(None)
    assert not is_agent_branch("agent-foo")  # bare agent-* without slash


def test_is_agent_workspace_path_matches() -> None:
    assert is_agent_workspace_path(
        "/home/user/.worktrees/org/repo/agent-abc/worker",
        "/home/user/.worktrees/org/repo",
    )
    assert is_agent_workspace_path(
        "/home/user/.worktrees/repo/agent-abc/worker",
        "/home/user/.worktrees/repo",
    )
    assert not is_agent_workspace_path(
        "/home/user/.worktrees/org/repo/wt-ab/feature",
        "/home/user/.worktrees/org/repo",
    )
    assert not is_agent_workspace_path(
        "/home/user/.worktrees/org/repo/agent-abc",
        "/home/user/.worktrees/org/repo",
    )


# --------------------------------------------------------------------------- periodic task


@pytest.mark.asyncio
async def test_run_periodic_sweep_cancellation_is_clean(tmp_path: Path) -> None:
    """Cancelling the periodic sweep task must not raise."""
    task = asyncio.create_task(run_periodic_sweep(3600.0, worktrees_root=str(tmp_path / "nonexistent")))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass  # clean cancellation


@pytest.mark.asyncio
async def test_run_periodic_sweep_runs_and_suppresses_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The periodic sweep must run its pass and never propagate exceptions."""
    call_count = {"n": 0}

    def counting_sweep(_root: str | None = None) -> SweepResult:
        call_count["n"] += 1
        return SweepResult()

    monkeypatch.setattr("basecamp.hub.swarm.sweep.sweep_agent_worktrees", counting_sweep)
    task = asyncio.create_task(run_periodic_sweep(0.01, worktrees_root=str(tmp_path)))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert call_count["n"] >= 1


@pytest.mark.asyncio
async def test_run_periodic_sweep_swallows_sweep_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def raising_sweep(_root: str | None = None) -> SweepResult:
        raise RuntimeError("boom")

    monkeypatch.setattr("basecamp.hub.swarm.sweep.sweep_agent_worktrees", raising_sweep)
    task = asyncio.create_task(run_periodic_sweep(0.01, worktrees_root=str(tmp_path)))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass  # the exception was swallowed, not propagated


# --------------------------------------------------------------------------- server wiring


def test_resolve_sweep_interval_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BASECAMP_AGENT_SWEEP_INTERVAL_S", raising=False)
    assert _resolve_sweep_interval_s() == _DEFAULT_SWEEP_INTERVAL_S


def test_resolve_sweep_interval_custom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASECAMP_AGENT_SWEEP_INTERVAL_S", "120")
    assert _resolve_sweep_interval_s() == 120.0


def test_resolve_sweep_interval_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASECAMP_AGENT_SWEEP_INTERVAL_S", "0")
    assert _resolve_sweep_interval_s() is None


def test_resolve_sweep_interval_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASECAMP_AGENT_SWEEP_INTERVAL_S", "not-a-number")
    assert _resolve_sweep_interval_s() == _DEFAULT_SWEEP_INTERVAL_S


def test_create_server_passes_sweep_interval(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    server = create_server(
        str(tmp_path / "daemon.sock"),
        store,
        sweep_interval_s=42.0,
    )
    assert server._sweep_interval_s == 42.0


def test_create_server_defaults_sweep_interval_to_none(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    server = create_server(str(tmp_path / "daemon.sock"), store)
    assert server._sweep_interval_s is None
