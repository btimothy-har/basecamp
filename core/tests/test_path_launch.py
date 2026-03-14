"""Tests for path-based launch functionality."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from core.cli.launch import (
    DEFAULT_PATH_WORKING_STYLE,
    execute_launch,
    is_path_argument,
    resolve_path_argument,
)
from core.config import Config
from core.exceptions import DirectoryNotFoundError


class TestIsPathArgument:
    """Tests for path detection heuristic."""

    def test_dot(self) -> None:
        assert is_path_argument(".") is True

    def test_dot_slash(self) -> None:
        assert is_path_argument("./subdir") is True

    def test_double_dot(self) -> None:
        assert is_path_argument("..") is True

    def test_absolute_path(self) -> None:
        assert is_path_argument("/tmp/foo") is True

    def test_tilde_path(self) -> None:
        assert is_path_argument("~/projects/foo") is True

    def test_contains_slash(self) -> None:
        assert is_path_argument("foo/bar") is True

    def test_simple_project_name(self) -> None:
        assert is_path_argument("myproject") is False

    def test_hyphenated_project_name(self) -> None:
        assert is_path_argument("my-project") is False

    def test_underscored_project_name(self) -> None:
        assert is_path_argument("my_project") is False


class TestResolvePathArgument:
    """Tests for path resolution."""

    def test_valid_directory(self, tmp_path: Path) -> None:
        result = resolve_path_argument(str(tmp_path))
        assert result == tmp_path

    def test_dot_resolves_to_cwd(self) -> None:
        result = resolve_path_argument(".")
        assert result == Path.cwd()

    def test_nonexistent_path(self) -> None:
        with pytest.raises(DirectoryNotFoundError):
            resolve_path_argument("/nonexistent/path/that/does/not/exist")

    def test_file_not_directory(self, tmp_path: Path) -> None:
        file_path = tmp_path / "afile.txt"
        file_path.write_text("content")
        with pytest.raises(DirectoryNotFoundError):
            resolve_path_argument(str(file_path))

    def test_tilde_expansion(self) -> None:
        result = resolve_path_argument("~")
        assert result == Path.home()


class TestExecuteLaunchPathMode:
    """Tests for execute_launch with resolved_path."""

    def test_path_mode_uses_resolved_dir(self, non_git_dir: Path, tmp_path: Path) -> None:
        """Path mode should chdir to the resolved directory."""
        with (
            patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"),
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir") as mock_chdir,
            patch("os.execvp"),
        ):
            execute_launch(
                non_git_dir.name,
                Config(projects={}),
                resolved_path=non_git_dir,
            )
            mock_chdir.assert_called_once_with(non_git_dir)

    def test_path_mode_sets_basecamp_repo(self, non_git_dir: Path, tmp_path: Path) -> None:
        """Path mode should set BASECAMP_REPO to directory name for non-git dirs."""
        with (
            patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"),
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir"),
            patch("os.execvp"),
        ):
            execute_launch(
                non_git_dir.name,
                Config(projects={}),
                resolved_path=non_git_dir,
            )
        assert os.environ["BASECAMP_REPO"] == non_git_dir.name

    def test_path_mode_uses_repo_name_for_git(self, temp_git_repo: Path, tmp_path: Path) -> None:
        """Path mode should use git repo name for BASECAMP_REPO when in a git repo."""
        with (
            patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"),
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir"),
            patch("os.execvp"),
        ):
            execute_launch(
                temp_git_repo.name,
                Config(projects={}),
                resolved_path=temp_git_repo,
            )
        assert os.environ["BASECAMP_REPO"] == "test_repo"

    def test_path_mode_uses_engineering_working_style(self, non_git_dir: Path, tmp_path: Path) -> None:
        """Path mode should create a ProjectConfig with the default working style."""
        with (
            patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"),
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir"),
            patch("os.execvp"),
            patch("core.cli.launch.prompts") as mock_prompts,
        ):
            mock_prompts.assemble.return_value = ("prompt content", ["source"])
            execute_launch(
                non_git_dir.name,
                Config(projects={}),
                resolved_path=non_git_dir,
            )
            project_arg = mock_prompts.assemble.call_args[0][0]
            assert project_arg.working_style == DEFAULT_PATH_WORKING_STYLE

    def test_path_mode_with_resume(self, non_git_dir: Path, tmp_path: Path) -> None:
        """Path mode should pass --resume to claude when resume=True."""
        with (
            patch("core.git.worktrees.WORKTREES_DIR", tmp_path / "worktrees"),
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
        ):
            execute_launch(
                non_git_dir.name,
                Config(projects={}),
                resume=True,
                resolved_path=non_git_dir,
            )
            # --resume appears either as a direct arg (in-tmux) or inside the
            # bash -c shell command string (tmux-wrapped)
            args = mock_execvp.call_args[0][1]
            if args[0] == "tmux":
                shell_cmd = args[-1]  # bash -c "<shell_cmd>"
                assert "--resume" in shell_cmd
            else:
                assert "--resume" in args
