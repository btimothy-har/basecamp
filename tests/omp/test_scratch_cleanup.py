from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from basecamp.omp import scratch_cleanup
from basecamp.omp.detached_run import CleanupFailure
from basecamp.omp.snapshot import WorkspaceSnapshot, capture_snapshot, restore_snapshot


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _workspace(tmp_path: Path, *, dirty: bool = False) -> tuple[Path, Path, WorkspaceSnapshot]:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-q")
    (source / "tracked.txt").write_text("base\n")
    _git(source, "add", "tracked.txt")
    _git(
        source,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        "initial",
    )
    if dirty:
        (source / "tracked.txt").write_text("staged\n")
        _git(source, "add", "tracked.txt")
        (source / "tracked.txt").write_text("staged and unstaged\n")
        (source / "untracked.txt").write_text("untracked\n")
    snapshot = capture_snapshot(source, tmp_path / "snapshot", "a" * 32)
    workspace = tmp_path / "workspace"
    _git(source, "worktree", "add", "--detach", "--quiet", str(workspace), snapshot.head)
    restore_snapshot(snapshot, workspace)
    return source, workspace, snapshot


def test_cleanup_removes_unchanged_detached_scratch(tmp_path: Path) -> None:
    source, workspace, snapshot = _workspace(tmp_path)

    result = scratch_cleanup.cleanup_automatic_workspace(source, workspace, snapshot)

    assert result.retained_reason is None
    assert result.failure is None
    assert not workspace.exists()


def test_cleanup_removes_scratch_cleaned_after_native_handoff(tmp_path: Path) -> None:
    source, workspace, snapshot = _workspace(tmp_path, dirty=True)
    _git(workspace, "reset", "--hard", "HEAD")
    _git(workspace, "clean", "-fd")

    result = scratch_cleanup.cleanup_automatic_workspace(source, workspace, snapshot)

    assert result.retained_reason is None
    assert result.failure is None
    assert not workspace.exists()


def test_cleanup_retains_modified_scratch(tmp_path: Path) -> None:
    source, workspace, snapshot = _workspace(tmp_path)
    (workspace / "tracked.txt").write_text("changed\n")

    result = scratch_cleanup.cleanup_automatic_workspace(source, workspace, snapshot)

    assert result.retained_reason == "it contains changes, commits, or unverifiable Git state"
    assert result.failure is None
    assert workspace.exists()


def test_cleanup_retains_detached_commit(tmp_path: Path) -> None:
    source, workspace, snapshot = _workspace(tmp_path)
    (workspace / "committed.txt").write_text("retained\n")
    _git(workspace, "add", "committed.txt")
    _git(
        workspace,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        "detached",
    )

    result = scratch_cleanup.cleanup_automatic_workspace(source, workspace, snapshot)

    assert result.retained_reason == "it contains changes, commits, or unverifiable Git state"
    assert result.failure is None
    assert workspace.exists()


def test_cleanup_retains_branch_attached_scratch(tmp_path: Path) -> None:
    source, workspace, snapshot = _workspace(tmp_path)
    _git(workspace, "switch", "-qc", "durable")

    result = scratch_cleanup.cleanup_automatic_workspace(source, workspace, snapshot)

    assert result.retained_reason == "it is attached to branch durable"
    assert result.failure is None
    assert workspace.exists()


def test_cleanup_retains_when_branch_inspection_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source, workspace, snapshot = _workspace(tmp_path)

    def fail(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 128, "", "broken repository")

    monkeypatch.setattr(scratch_cleanup.subprocess, "run", fail)

    result = scratch_cleanup.cleanup_automatic_workspace(source, workspace, snapshot)

    assert result.retained_reason == "its branch state could not be inspected: broken repository"
    assert result.failure is None
    assert workspace.exists()


def test_cleanup_surfaces_targeted_removal_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source, workspace, snapshot = _workspace(tmp_path)
    failure = CleanupFailure(detail="locked", recovery_command="git targeted cleanup")
    monkeypatch.setattr(scratch_cleanup, "remove_workspace", lambda *_args: failure)

    result = scratch_cleanup.cleanup_automatic_workspace(source, workspace, snapshot)

    assert result.retained_reason is None
    assert result.failure == failure
    assert workspace.exists()
