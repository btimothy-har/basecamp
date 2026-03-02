"""Tests for the worktrees module."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from core.exceptions import WorktreeNotFoundError
from core.git import (
    WorktreeInfo,
    create_worktree,
    get_or_create_worktree,
    get_repo_name,
    get_worktree,
    is_git_repo,
    list_all_worktrees,
    list_worktrees,
    remove_all_worktrees,
    remove_worktree,
)


class TestIsGitRepo:
    """Tests for is_git_repo function."""

    def test_is_git_repo_true(self, temp_git_repo: Path) -> None:
        """Test that a git repository is detected."""
        assert is_git_repo(temp_git_repo) is True

    def test_is_git_repo_false(self, non_git_dir: Path) -> None:
        """Test that a non-git directory is detected."""
        assert is_git_repo(non_git_dir) is False


class TestGetRepoName:
    """Tests for get_repo_name function."""

    def test_get_repo_name_from_git_repo(self, temp_git_repo: Path) -> None:
        """Test getting repo name from a git repository."""
        repo_name = get_repo_name(temp_git_repo)
        assert repo_name == temp_git_repo.name

    def test_get_repo_name_fallback(self, non_git_dir: Path) -> None:
        """Test fallback to directory name for non-git directories."""
        repo_name = get_repo_name(non_git_dir)
        assert repo_name == non_git_dir.name


class TestWorktreeInfo:
    """Tests for WorktreeInfo dataclass."""

    def test_to_dict(self) -> None:
        """Test converting WorktreeInfo to dictionary."""
        info = WorktreeInfo(
            name="auth",
            path=Path("/tmp/worktree"),
            branch="wt/auth",
            created_at=datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC),
            project="myproject",
            repo_name="my-repo",
            source_dir=Path("/tmp/source"),
        )
        data = info.to_dict()

        assert data["name"] == "auth"
        assert data["path"] == "/tmp/worktree"
        assert data["branch"] == "wt/auth"
        assert data["created_at"] == "2025-01-15T10:30:00+00:00"
        assert data["project"] == "myproject"
        assert data["repo_name"] == "my-repo"
        assert data["source_dir"] == "/tmp/source"

    def test_from_dict(self) -> None:
        """Test creating WorktreeInfo from dictionary."""
        data = {
            "name": "auth",
            "path": "/tmp/worktree",
            "branch": "wt/auth",
            "created_at": "2025-01-15T10:30:00+00:00",
            "project": "myproject",
            "repo_name": "my-repo",
            "source_dir": "/tmp/source",
        }
        info = WorktreeInfo.from_dict(data)

        assert info.name == "auth"
        assert info.path == Path("/tmp/worktree")
        assert info.branch == "wt/auth"
        assert info.created_at == datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC)
        assert info.project == "myproject"
        assert info.repo_name == "my-repo"
        assert info.source_dir == Path("/tmp/source")

    def test_from_dict_without_optional_fields(self) -> None:
        """Test creating WorktreeInfo without optional fields."""
        data = {
            "name": "auth",
            "path": "/tmp/worktree",
            "branch": "wt/auth",
            "created_at": "2025-01-15T10:30:00",
            "project": "myproject",
        }
        info = WorktreeInfo.from_dict(data)

        assert info.repo_name == ""
        assert info.source_dir == Path("")


class TestCreateWorktree:
    """Tests for create_worktree function."""

    def test_create_worktree_success(self, temp_git_repo: Path, tmp_path: Path) -> None:
        """Test successful worktree creation with label."""
        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            info = create_worktree(temp_git_repo, "testproject", "auth")

        assert info.name == "auth"
        assert info.branch == "wt/auth"
        assert info.project == "testproject"
        assert info.repo_name == temp_git_repo.name
        assert info.path.exists()
        # Metadata should be stored in .meta directory, not in worktree
        meta_path = tmp_path / "worktrees" / temp_git_repo.name / ".meta" / "auth.json"
        assert meta_path.exists()

    def test_create_worktree_metadata_saved(self, temp_git_repo: Path, tmp_path: Path) -> None:
        """Test that metadata is saved correctly in .meta directory."""
        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            create_worktree(temp_git_repo, "testproject", "feature")

        # Metadata stored in .meta directory, not inside worktree
        meta_path = tmp_path / "worktrees" / temp_git_repo.name / ".meta" / "feature.json"
        meta_data = json.loads(meta_path.read_text())

        assert meta_data["name"] == "feature"
        assert meta_data["project"] == "testproject"
        assert meta_data["repo_name"] == temp_git_repo.name

    def test_create_worktree_organized_by_repo(self, temp_git_repo: Path, tmp_path: Path) -> None:
        """Test that worktrees are organized by repo name."""
        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            info = create_worktree(temp_git_repo, "testproject", "myfeature")

        # Worktree should be at worktrees/<repo_name>/<label>
        expected_parent = tmp_path / "worktrees" / temp_git_repo.name
        assert info.path.parent == expected_parent


class TestGetOrCreateWorktree:
    """Tests for get_or_create_worktree function."""

    def test_creates_new_worktree(self, temp_git_repo: Path, tmp_path: Path) -> None:
        """Test that a new worktree is created if it doesn't exist."""
        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            info, created = get_or_create_worktree(temp_git_repo, "testproject", "newfeature")

        assert created is True
        assert info.name == "newfeature"
        assert info.path.exists()

    def test_returns_existing_worktree(self, temp_git_repo: Path, tmp_path: Path) -> None:
        """Test that an existing worktree is returned."""
        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            # Create first
            first_info = create_worktree(temp_git_repo, "testproject", "existing")
            # Get or create should return existing
            info, created = get_or_create_worktree(temp_git_repo, "testproject", "existing")

        assert created is False
        assert info.name == "existing"
        assert info.path == first_info.path


class TestGetWorktree:
    """Tests for get_worktree function."""

    def test_get_worktree_exists(self, temp_git_repo: Path, tmp_path: Path) -> None:
        """Test getting an existing worktree."""
        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            created = create_worktree(temp_git_repo, "testproject", "myworktree")
            # Use repo_name to retrieve
            retrieved = get_worktree(temp_git_repo.name, created.name)

        assert retrieved is not None
        assert retrieved.name == created.name
        assert retrieved.branch == created.branch

    def test_get_worktree_not_exists(self, tmp_path: Path) -> None:
        """Test getting a non-existent worktree."""
        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            result = get_worktree("some-repo", "nonexistent")

        assert result is None


class TestListWorktrees:
    """Tests for list_worktrees function."""

    def test_list_worktrees_empty(self, tmp_path: Path) -> None:
        """Test listing worktrees for a repo with none."""
        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            result = list_worktrees("some-repo")

        assert result == []

    def test_list_worktrees_multiple(self, temp_git_repo: Path, tmp_path: Path) -> None:
        """Test listing multiple worktrees."""
        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            wt1 = create_worktree(temp_git_repo, "testproject", "first")
            wt2 = create_worktree(temp_git_repo, "testproject", "second")
            result = list_worktrees(temp_git_repo.name)

        assert len(result) == 2
        names = [wt.name for wt in result]
        assert wt1.name in names
        assert wt2.name in names

    def test_list_worktrees_sorted_by_creation_time(self, temp_git_repo: Path, tmp_path: Path) -> None:
        """Test that worktrees are sorted by creation time (newest first)."""

        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            wt1 = create_worktree(temp_git_repo, "testproject", "first")
            time.sleep(0.1)  # Small delay to ensure different timestamps
            wt2 = create_worktree(temp_git_repo, "testproject", "second")
            result = list_worktrees(temp_git_repo.name)

        assert len(result) == 2
        # Newest first
        assert result[0].name == wt2.name
        assert result[1].name == wt1.name


class TestRemoveWorktree:
    """Tests for remove_worktree function."""

    def test_remove_worktree_success(self, temp_git_repo: Path, tmp_path: Path) -> None:
        """Test successful worktree removal."""
        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            info = create_worktree(temp_git_repo, "testproject", "toremove")
            assert info.path.exists()

            remove_worktree(temp_git_repo.name, info.name, force=True)
            assert not info.path.exists()

    def test_remove_worktree_not_found(self, tmp_path: Path) -> None:
        """Test removing a non-existent worktree."""
        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            with pytest.raises(WorktreeNotFoundError):
                remove_worktree("some-repo", "nonexistent")


class TestRemoveAllWorktrees:
    """Tests for remove_all_worktrees function."""

    def test_remove_all_worktrees_success(self, temp_git_repo: Path, tmp_path: Path) -> None:
        """Test removing all worktrees for a repo."""
        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            wt1 = create_worktree(temp_git_repo, "testproject", "first")
            wt2 = create_worktree(temp_git_repo, "testproject", "second")

            removed = remove_all_worktrees(temp_git_repo.name, force=True)

        assert len(removed) == 2
        assert wt1.name in removed
        assert wt2.name in removed
        assert not wt1.path.exists()
        assert not wt2.path.exists()

    def test_remove_all_worktrees_empty(self, tmp_path: Path) -> None:
        """Test removing all worktrees when none exist."""
        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            removed = remove_all_worktrees("some-repo")

        assert removed == []


class TestListAllWorktrees:
    """Tests for list_all_worktrees function."""

    def test_list_all_worktrees_empty(self, tmp_path: Path) -> None:
        """Test listing all worktrees when none exist."""
        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            result = list_all_worktrees()

        assert result == {}

    def test_list_all_worktrees_single_repo(self, temp_git_repo: Path, tmp_path: Path) -> None:
        """Test listing all worktrees with a single repo."""
        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            wt = create_worktree(temp_git_repo, "testproject", "myworktree")
            result = list_all_worktrees()

        assert temp_git_repo.name in result
        assert len(result[temp_git_repo.name]) == 1
        assert result[temp_git_repo.name][0].name == wt.name

    def test_list_all_worktrees_skips_hidden_dirs(self, temp_git_repo: Path, tmp_path: Path) -> None:
        """Test that hidden directories (like .meta) are skipped."""
        worktrees_dir = tmp_path / "worktrees"
        with patch("core.git.worktrees.WORKTREES_DIR", worktrees_dir):
            create_worktree(temp_git_repo, "testproject", "myworktree")
            # Create a hidden directory that should be skipped
            hidden_dir = worktrees_dir / ".hidden-dir"
            hidden_dir.mkdir(parents=True)
            result = list_all_worktrees()

        # Should only contain the repo, not the hidden directory
        assert list(result.keys()) == [temp_git_repo.name]
        assert ".hidden-dir" not in result
