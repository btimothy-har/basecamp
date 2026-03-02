"""Tests for launch integration with worktrees."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from core.cli.launch import execute_launch
from core.config import Config, ProjectConfig
from core.exceptions import NotAGitRepoError
from core.git import create_worktree


class TestExecuteLaunchWorktreeIntegration:
    """Tests for execute_launch with worktree integration."""

    @pytest.fixture
    def mock_config(self) -> Config:
        """Create a mock config for testing."""
        return Config(
            projects={
                "testproject": ProjectConfig(
                    dirs=["~/test/project"],
                    description="Test project",
                ),
            }
        )

    def test_launch_without_label_uses_original_dir(
        self, temp_git_repo: Path, mock_config: Config, tmp_path: Path
    ) -> None:
        """Test that launch without label uses the original directory (no worktree)."""
        mock_config.projects["testproject"].dirs = [str(temp_git_repo)]

        with (
            patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"),
            patch("core.cli.launch.validate_dirs") as mock_validate,
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir") as mock_chdir,
            patch("os.execvp") as mock_execvp,
        ):
            mock_validate.return_value = [temp_git_repo]

            execute_launch("testproject", mock_config, resume=True)

            # Verify chdir was called with original directory (no worktree created)
            chdir_path = mock_chdir.call_args[0][0]
            assert chdir_path == temp_git_repo

            # Verify execvp was called
            mock_execvp.assert_called_once()

    def test_launch_with_label_creates_worktree(self, temp_git_repo: Path, mock_config: Config, tmp_path: Path) -> None:
        """Test that launch with label creates a worktree."""
        mock_config.projects["testproject"].dirs = [str(temp_git_repo)]

        with (
            patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"),
            patch("core.cli.launch.validate_dirs") as mock_validate,
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir") as mock_chdir,
            patch("os.execvp"),
        ):
            mock_validate.return_value = [temp_git_repo]

            execute_launch("testproject", mock_config, resume=True, label="auth")

            # Verify the worktree path is used (label is the directory name)
            chdir_path = str(mock_chdir.call_args[0][0])
            assert chdir_path.endswith("/auth")
            assert tmp_path.name in chdir_path

    def test_launch_with_label_reuses_existing_worktree(
        self, temp_git_repo: Path, mock_config: Config, tmp_path: Path
    ) -> None:
        """Test that launch with label re-enters existing worktree."""

        mock_config.projects["testproject"].dirs = [str(temp_git_repo)]

        with patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"):
            # Create a worktree first
            existing_wt = create_worktree(temp_git_repo, "testproject", "existing")

        with (
            patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"),
            patch("core.cli.launch.validate_dirs") as mock_validate,
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir") as mock_chdir,
            patch("os.execvp"),
        ):
            mock_validate.return_value = [temp_git_repo]

            # Use same label - should re-enter existing worktree
            execute_launch("testproject", mock_config, resume=True, label="existing")

            # Verify chdir was called with the existing worktree path
            chdir_path = mock_chdir.call_args[0][0]
            assert chdir_path == existing_wt.path

    def test_basecamp_repo_uses_repo_name_without_label(
        self, temp_git_repo: Path, mock_config: Config, tmp_path: Path
    ) -> None:
        """Test that BASECAMP_REPO is set to repo name, not dir name, for git repos."""
        mock_config.projects["testproject"].dirs = [str(temp_git_repo)]

        with (
            patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"),
            patch("core.cli.launch.validate_dirs") as mock_validate,
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir"),
            patch("os.execvp"),
        ):
            mock_validate.return_value = [temp_git_repo]
            execute_launch("testproject", mock_config)

        assert os.environ["BASECAMP_REPO"] == "test_repo"

    def test_basecamp_repo_uses_repo_name_with_label(
        self, temp_git_repo: Path, mock_config: Config, tmp_path: Path
    ) -> None:
        """Test that BASECAMP_REPO uses repo name (not worktree label) when label is set."""
        mock_config.projects["testproject"].dirs = [str(temp_git_repo)]

        with (
            patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"),
            patch("core.cli.launch.validate_dirs") as mock_validate,
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir"),
            patch("os.execvp"),
        ):
            mock_validate.return_value = [temp_git_repo]
            execute_launch("testproject", mock_config, label="auth")

        # Must be repo name, not the worktree label
        assert os.environ["BASECAMP_REPO"] == "test_repo"

    def test_basecamp_repo_falls_back_to_dir_name_for_non_git(
        self, non_git_dir: Path, mock_config: Config, tmp_path: Path
    ) -> None:
        """Test that BASECAMP_REPO falls back to directory name for non-git repos."""
        mock_config.projects["testproject"].dirs = [str(non_git_dir)]

        with (
            patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"),
            patch("core.cli.launch.validate_dirs") as mock_validate,
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir"),
            patch("os.execvp"),
        ):
            mock_validate.return_value = [non_git_dir]
            execute_launch("testproject", mock_config)

        assert os.environ["BASECAMP_REPO"] == "not_a_repo"

    def test_launch_with_label_on_non_git_raises(self, non_git_dir: Path, mock_config: Config, tmp_path: Path) -> None:
        """Test that using label on non-git directory raises error."""
        mock_config.projects["testproject"].dirs = [str(non_git_dir)]

        with (
            patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"),
            patch("core.cli.launch.validate_dirs") as mock_validate,
        ):
            mock_validate.return_value = [non_git_dir]

            with pytest.raises(NotAGitRepoError):
                execute_launch("testproject", mock_config, resume=True, label="auth")

    def test_launch_non_git_without_label_succeeds(
        self, non_git_dir: Path, mock_config: Config, tmp_path: Path
    ) -> None:
        """Test that launch without label works for non-git directories."""
        mock_config.projects["testproject"].dirs = [str(non_git_dir)]

        with (
            patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"),
            patch("core.cli.launch.validate_dirs") as mock_validate,
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir") as mock_chdir,
            patch("os.execvp"),
        ):
            mock_validate.return_value = [non_git_dir]

            execute_launch("testproject", mock_config, resume=True)

            # Verify chdir was called with original directory
            chdir_path = mock_chdir.call_args[0][0]
            assert chdir_path == non_git_dir
