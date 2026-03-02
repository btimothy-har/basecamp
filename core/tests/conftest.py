"""Test fixtures for basecamp tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary git repository.

    Yields:
        Path to the git repository root.
    """
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        capture_output=True,
        check=True,
    )

    # Create initial commit (required for worktrees)
    readme = repo_path / "README.md"
    readme.write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        capture_output=True,
        check=True,
    )

    yield repo_path

    # Cleanup: remove any worktrees we created
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        check=False,
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("worktree ") and str(tmp_path) in line:
            wt_path = line.replace("worktree ", "")
            if wt_path != str(repo_path):
                subprocess.run(
                    ["git", "worktree", "remove", "--force", wt_path],
                    check=False,
                    cwd=repo_path,
                    capture_output=True,
                )


@pytest.fixture
def non_git_dir(tmp_path: Path) -> Path:
    """Create a temporary directory that is not a git repository.

    Returns:
        Path to the non-git directory.
    """
    non_git_path = tmp_path / "not_a_repo"
    non_git_path.mkdir()
    (non_git_path / "some_file.txt").write_text("Not a git repo\n")
    return non_git_path
