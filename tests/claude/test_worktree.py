"""Tests for basecamp.claude.worktree — provisioning primitives (real git in tmp)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from basecamp.claude.worktree import (
    WorktreeError,
    branch_exists,
    copilot_worktree_target,
    detect_default_branch,
    get_or_create_worktree,
    normalize_slug,
)


def _init_repo(path: Path, default: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", f"--initial-branch={default}"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.co"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=path, check=True)


def test_normalize_slug() -> None:
    assert normalize_slug("Auth Refactor!!") == "auth-refactor"
    assert normalize_slug("  Hello   World -- Foo ") == "hello-world-foo"
    assert normalize_slug("!!!") == "worktree"  # fallback


def test_copilot_worktree_target_label_and_branch() -> None:
    t = copilot_worktree_target("Auth Refactor", "brave-otter-fox", "btimothy")
    assert t.label == "copilot/brave-otter-fox"
    assert t.branch == "bt/auth-refactor"


def test_copilot_target_user_prefix_fallback() -> None:
    # a user id with <2 alnum chars falls back to 'un'
    assert copilot_worktree_target("work", "a-b-c", "!").branch.startswith("un/")


def test_copilot_target_caps_label_to_32() -> None:
    t = copilot_worktree_target("a" * 100, "s-l-g", "btimothy")
    assert len(t.branch) <= 32


def test_detect_default_branch_main(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, default="main")
    assert detect_default_branch(str(repo)) == "main"


def test_branch_exists(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    assert branch_exists(str(repo), "main") is True
    assert branch_exists(str(repo), "nope") is False


def test_get_or_create_worktree_creates_then_reuses(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    home = tmp_path / "home"

    first = get_or_create_worktree(str(repo), "acme/web-app", "copilot/a-b-c", "bt/work", home=home)
    assert first.created is True
    assert first.label == "copilot/a-b-c"
    assert first.branch == "bt/work"
    assert Path(first.path).is_dir()
    # under ~/.worktrees/<org>/<name>/<label>/
    assert first.path.endswith("/.worktrees/acme/web-app/copilot/a-b-c")

    second = get_or_create_worktree(str(repo), "acme/web-app", "copilot/a-b-c", "bt/work", home=home)
    assert second.created is False  # idempotent reuse by label
    assert second.path == first.path


def test_get_or_create_worktree_does_not_leak_dirty_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    home = tmp_path / "home"
    # dirty the main checkout: modify tracked + add untracked
    (repo / "README.md").write_text("MODIFIED\n")
    (repo / "wip.txt").write_text("uncommitted\n")

    result = get_or_create_worktree(str(repo), "acme/web-app", "copilot/a-b-c", "bt/work", home=home)
    wt = Path(result.path)
    # new worktree has the clean committed tip, not the dirty working state
    assert (wt / "README.md").read_text() == "x\n"
    assert not (wt / "wip.txt").exists()


def test_get_or_create_worktree_bad_repo_raises(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(WorktreeError):
        get_or_create_worktree(str(plain), "acme/web", "copilot/a-b-c", "bt/work", home=tmp_path / "home")
