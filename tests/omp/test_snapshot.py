"""Behavioral coverage for immutable scratch snapshots."""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from basecamp.core.exceptions import LauncherError
from basecamp.omp import snapshot as snapshot_module
from basecamp.omp.snapshot import capture_snapshot, delete_snapshot_ref, matches_snapshot, restore_snapshot


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        capture_output=True,
    )


def _commit(root: Path, message: str) -> None:
    _git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        message,
    )


def _init_repo(root: Path) -> Path:
    root.mkdir()
    _git(root, "init", "-q")
    (root / "tracked.txt").write_text("base\n")
    _git(root, "add", "tracked.txt")
    _commit(root, "initial")
    return root


def _dirty_fixture(root: Path) -> bytes:
    (root / ".gitignore").write_text("ignored-*\n")
    (root / "delete.txt").write_text("delete\n")
    (root / "binary.bin").write_bytes(b"\x00base\xff")
    (root / "executable.sh").write_text("#!/bin/sh\nexit 0\n")
    (root / "link").symlink_to("tracked.txt")
    (root / "ignored-tracked.txt").write_text("tracked ignored\n")
    _git(root, "add", ".gitignore", "delete.txt", "binary.bin", "executable.sh", "link", "-f", "ignored-tracked.txt")
    _commit(root, "fixture")

    (root / "tracked.txt").write_text("staged\n")
    _git(root, "add", "tracked.txt")
    (root / "tracked.txt").write_text("staged and unstaged\n")
    (root / "delete.txt").unlink()
    _git(root, "add", "delete.txt")
    (root / "added.txt").write_text("staged add\n")
    _git(root, "add", "added.txt")
    (root / "binary.bin").write_bytes(b"\x00changed\xfe")
    (root / "link").unlink()
    (root / "link").symlink_to("added.txt")
    os.chmod(root / "executable.sh", stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    _git(root, "add", "executable.sh")
    (root / "ignored-tracked.txt").write_text("changed despite ignore\n")
    (root / "untracked.txt").write_text("untracked\n")
    (root / "intent.txt").write_text("intent\n")
    _git(root, "add", "-N", "intent.txt")
    (root / "ignored-intent.txt").write_text("ignored intent\n")
    _git(root, "add", "-N", "-f", "ignored-intent.txt")
    return _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout


def _restore(root: Path, snapshot_dir: Path, target: Path):
    snapshot = capture_snapshot(root, snapshot_dir, "0123456789abcdef0123456789abcdef")
    _git(root, "worktree", "add", "--detach", "-q", str(target), snapshot.head)
    restore_snapshot(snapshot, target)
    return snapshot


def test_snapshot_restores_content_staging_modes_and_intent_without_source_mutation(tmp_path: Path) -> None:
    source = _init_repo(tmp_path / "source")
    expected_status = _dirty_fixture(source)
    source_index = Path(
        _git(source, "rev-parse", "--path-format=absolute", "--git-path", "index").stdout.decode().strip()
    )
    original_index = source_index.read_bytes()
    original_head = _git(source, "rev-parse", "HEAD").stdout
    original_branch = _git(source, "symbolic-ref", "--short", "HEAD").stdout
    original_stashes = _git(source, "stash", "list").stdout

    snapshot = _restore(source, tmp_path / "snapshot", tmp_path / "target")
    target = tmp_path / "target"
    assert stat.S_IMODE((tmp_path / "snapshot").stat().st_mode) == 0o700
    assert stat.S_IMODE(snapshot.index_path.stat().st_mode) == 0o600

    assert snapshot.has_uncommitted_work
    assert matches_snapshot(snapshot, target)
    assert _git(target, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == expected_status
    assert (target / "tracked.txt").read_text() == "staged and unstaged\n"
    assert (target / "binary.bin").read_bytes() == b"\x00changed\xfe"
    assert os.readlink(target / "link") == "added.txt"
    assert os.access(target / "executable.sh", os.X_OK)
    assert (target / "ignored-tracked.txt").read_text() == "changed despite ignore\n"
    assert (target / "ignored-intent.txt").read_text() == "ignored intent\n"
    visible_intent = _git(target, "diff", "--cached", "--ita-visible-in-index", "HEAD", "--", "intent.txt").stdout
    invisible_intent = _git(target, "diff", "--cached", "--ita-invisible-in-index", "HEAD", "--", "intent.txt").stdout
    assert visible_intent
    assert not invisible_intent
    assert _git(target, "rev-parse", "HEAD").stdout == original_head
    assert _git(source, "rev-parse", "HEAD").stdout == original_head
    assert _git(source, "symbolic-ref", "--short", "HEAD").stdout == original_branch
    assert _git(source, "stash", "list").stdout == original_stashes
    assert source_index.read_bytes() == original_index
    snapshot_commit = _git(source, "rev-parse", snapshot.snapshot_ref).stdout.strip()
    assert _git(target, "merge-base", "--is-ancestor", snapshot_commit.decode(), "HEAD", check=False).returncode == 1


def test_delete_snapshot_ref_releases_private_recovery_objects(tmp_path: Path) -> None:
    source = _init_repo(tmp_path / "source")
    snapshot = capture_snapshot(source, tmp_path / "snapshot", "a" * 32)
    assert _git(source, "rev-parse", "--verify", snapshot.snapshot_ref, check=False).returncode == 0

    delete_snapshot_ref(snapshot, source)

    assert _git(source, "rev-parse", "--verify", snapshot.snapshot_ref, check=False).returncode != 0


def test_delete_snapshot_ref_reports_failure_without_raising(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = _init_repo(tmp_path / "source")
    snapshot = capture_snapshot(source, tmp_path / "snapshot", "b" * 32)

    def fail(*_args: object, **_kwargs: object) -> bytes:
        message = "ref cleanup failed"
        raise LauncherError(message)

    monkeypatch.setattr(snapshot_module, "_run_git", fail)

    assert delete_snapshot_ref(snapshot, source) == "ref cleanup failed"


def test_snapshot_commit_ignores_user_signing_configuration(tmp_path: Path) -> None:
    source = _init_repo(tmp_path / "source")
    _git(source, "config", "commit.gpgsign", "true")
    _git(source, "config", "gpg.program", "false")

    snapshot = capture_snapshot(source, tmp_path / "snapshot", "c" * 32)
    assert _git(source, "rev-parse", "--verify", snapshot.snapshot_ref).returncode == 0


def test_snapshot_ignores_inherited_git_location_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = _init_repo(tmp_path / "source")
    redirected_index = tmp_path / "redirected-index"
    redirected_index.write_text("not a Git index")
    monkeypatch.setenv("GIT_INDEX_FILE", str(redirected_index))

    snapshot = capture_snapshot(source, tmp_path / "snapshot", "d" * 32)

    monkeypatch.delenv("GIT_INDEX_FILE")
    assert matches_snapshot(snapshot, source)
    assert redirected_index.read_text() == "not a Git index"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda root: (root / "tracked.txt").write_text("later bytes\n"),
        lambda root: (root / "new.txt").write_text("new untracked\n"),
        lambda root: _git(root, "add", "tracked.txt"),
        lambda root: _git(root, "reset", "intent.txt"),
        lambda root: (root / "ignored-intent.txt").write_text("later ignored intent\n"),
    ],
)
def test_snapshot_comparison_detects_new_work(
    tmp_path: Path,
    mutate: Callable[[Path], object],
) -> None:
    source = _init_repo(tmp_path / "source")
    _dirty_fixture(source)
    snapshot = _restore(source, tmp_path / "snapshot", tmp_path / "target")

    mutate(tmp_path / "target")

    assert not matches_snapshot(snapshot, tmp_path / "target")


def test_snapshot_comparison_ignores_index_stat_refresh(tmp_path: Path) -> None:
    source = _init_repo(tmp_path / "source")
    snapshot = _restore(source, tmp_path / "snapshot", tmp_path / "target")

    _git(tmp_path / "target", "update-index", "--refresh")

    assert matches_snapshot(snapshot, tmp_path / "target")


@pytest.mark.parametrize("feature", ["conflict", "sparse", "skip-worktree", "embedded-repository"])
def test_snapshot_rejects_unrecoverable_checkout_shapes(tmp_path: Path, feature: str) -> None:
    source = _init_repo(tmp_path / "source")
    if feature == "conflict":
        initial_branch = _git(source, "symbolic-ref", "--short", "HEAD").stdout.decode().strip()
        _git(source, "switch", "-qc", "other")
        (source / "tracked.txt").write_text("other\n")
        _git(source, "add", "tracked.txt")
        _commit(source, "other")
        _git(source, "switch", "-q", initial_branch)
        (source / "tracked.txt").write_text("main\n")
        _git(source, "add", "tracked.txt")
        _commit(source, "main")
        _git(source, "merge", "other", check=False)
    elif feature == "sparse":
        _git(source, "config", "core.sparseCheckout", "true")
    elif feature == "skip-worktree":
        _git(source, "update-index", "--skip-worktree", "tracked.txt")
    else:
        embedded = source / "embedded"
        _init_repo(embedded)

    with pytest.raises(LauncherError, match="Use bomp --direct"):
        capture_snapshot(source, tmp_path / "snapshot", "fedcba9876543210fedcba9876543210")


def test_snapshot_normalizes_split_index_without_writing_source_index(tmp_path: Path) -> None:
    source = _init_repo(tmp_path / "source")
    _git(source, "update-index", "--split-index")
    _git(source, "update-index", "--untracked-cache")
    source_index = Path(
        _git(source, "rev-parse", "--path-format=absolute", "--git-path", "index").stdout.decode().strip()
    )
    original_index = source_index.read_bytes()

    snapshot = _restore(source, tmp_path / "snapshot", tmp_path / "target")

    assert matches_snapshot(snapshot, tmp_path / "target")
    assert source_index.read_bytes() == original_index


def test_snapshot_accepts_clean_initialized_and_uninitialized_submodules(tmp_path: Path) -> None:
    dependency = _init_repo(tmp_path / "dependency")
    source = _init_repo(tmp_path / "source")
    _git(
        source,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(dependency),
        "modules/dependency",
    )
    _commit(source, "submodule")

    initialized = capture_snapshot(
        source,
        tmp_path / "initialized-snapshot",
        "11111111111111111111111111111111",
    )
    assert not initialized.has_uncommitted_work

    _git(source, "submodule", "deinit", "-q", "-f", "--all")
    uninitialized = capture_snapshot(
        source,
        tmp_path / "uninitialized-snapshot",
        "22222222222222222222222222222222",
    )
    assert not uninitialized.has_uncommitted_work


def test_snapshot_rejects_dirty_initialized_submodule(tmp_path: Path) -> None:
    dependency = _init_repo(tmp_path / "dependency")
    source = _init_repo(tmp_path / "source")
    _git(
        source,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(dependency),
        "modules/dependency",
    )
    _commit(source, "submodule")
    (source / "modules" / "dependency" / "tracked.txt").write_text("dirty\n")

    with pytest.raises(LauncherError, match="submodule modules/dependency is changed"):
        capture_snapshot(
            source,
            tmp_path / "snapshot",
            "33333333333333333333333333333333",
        )
