"""Tests for dispatch command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from core.cli.dispatch import execute_dispatch
from core.config import Config, ProjectConfig
from core.exceptions import DispatchError, NotInTmuxError, TaskPromptNotFoundError


@pytest.fixture
def mock_config(temp_git_repo: Path) -> Config:
    """Create a config pointing at a real git repo."""
    return Config(
        projects={
            "testproject": ProjectConfig(
                dirs=[str(temp_git_repo)],
                description="Test project",
            ),
        }
    )


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """Create a task directory with prompt.md."""
    session_id = "test-session-123"
    task = tmp_path / "tasks" / session_id / "test-task"
    task.mkdir(parents=True)
    (task / "prompt.md").write_text("Implement the auth schema migration")
    return tmp_path / "tasks"


class TestExecuteDispatchValidation:
    """Tests for dispatch validation logic."""

    def test_raises_not_in_tmux(self, mock_config: Config) -> None:
        env = {"CLAUDE_SESSION_ID": "test-session-123"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(NotInTmuxError):
                execute_dispatch("testproject", mock_config, name="test-task")

    def test_raises_no_session_id(self, mock_config: Config) -> None:
        env = {"TMUX": "/tmp/tmux-1000/default,12345,0"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(DispatchError, match="CLAUDE_SESSION_ID"):
                execute_dispatch("testproject", mock_config, name="test-task")

    def test_raises_prompt_not_found(self, mock_config: Config, tmp_path: Path) -> None:
        env = {
            "TMUX": "/tmp/tmux-1000/default,12345,0",
            "CLAUDE_SESSION_ID": "test-session-123",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.cli.dispatch.TASKS_DIR", tmp_path / "tasks"),
        ):
            with pytest.raises(TaskPromptNotFoundError):
                execute_dispatch("testproject", mock_config, name="nonexistent-task")


class TestExecuteDispatchSuccess:
    """Tests for successful dispatch execution."""

    def test_dispatch_launches_tmux_pane(
        self, temp_git_repo: Path, mock_config: Config, task_dir: Path
    ) -> None:
        env = {
            "TMUX": "/tmp/tmux-1000/default,12345,0",
            "CLAUDE_SESSION_ID": "test-session-123",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.cli.dispatch.TASKS_DIR", task_dir),
            patch("core.cli.dispatch.validate_dirs") as mock_validate,
            patch("core.cli.dispatch.is_git_repo", return_value=True),
            patch("core.cli.dispatch.get_repo_name", return_value="test_repo"),
            patch("core.cli.dispatch.subprocess.run") as mock_run,
        ):
            mock_validate.return_value = [temp_git_repo]

            execute_dispatch("testproject", mock_config, name="test-task")

            # First call should be tmux split-window
            split_call = mock_run.call_args_list[0]
            cmd = split_call[0][0]
            assert cmd[0] == "tmux"
            assert cmd[1] == "split-window"
            assert "-v" in cmd

            # Verify env vars are passed
            cmd_str = " ".join(cmd)
            assert "BASECAMP_TASK_DIR=" in cmd_str
            assert "BASECAMP_REPO=test_repo" in cmd_str

            # Verify cwd is set to project directory
            assert "-c" in cmd
            c_idx = cmd.index("-c")
            assert cmd[c_idx + 1] == str(temp_git_repo)

    def test_dispatch_sets_pane_title(
        self, temp_git_repo: Path, mock_config: Config, task_dir: Path
    ) -> None:
        env = {
            "TMUX": "/tmp/tmux-1000/default,12345,0",
            "CLAUDE_SESSION_ID": "test-session-123",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.cli.dispatch.TASKS_DIR", task_dir),
            patch("core.cli.dispatch.validate_dirs") as mock_validate,
            patch("core.cli.dispatch.is_git_repo", return_value=True),
            patch("core.cli.dispatch.get_repo_name", return_value="test_repo"),
            patch("core.cli.dispatch.subprocess.run") as mock_run,
        ):
            mock_validate.return_value = [temp_git_repo]

            execute_dispatch("testproject", mock_config, name="test-task")

            # Second call should set pane title
            title_call = mock_run.call_args_list[1]
            cmd = title_call[0][0]
            assert cmd[0] == "tmux"
            assert "select-pane" in cmd
            assert "test-task" in cmd

    def test_dispatch_tmux_failure(
        self, temp_git_repo: Path, mock_config: Config, task_dir: Path
    ) -> None:
        import subprocess as sp

        env = {
            "TMUX": "/tmp/tmux-1000/default,12345,0",
            "CLAUDE_SESSION_ID": "test-session-123",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.cli.dispatch.TASKS_DIR", task_dir),
            patch("core.cli.dispatch.validate_dirs") as mock_validate,
            patch("core.cli.dispatch.is_git_repo", return_value=True),
            patch("core.cli.dispatch.get_repo_name", return_value="test_repo"),
            patch("core.cli.dispatch.subprocess.run") as mock_run,
        ):
            mock_validate.return_value = [temp_git_repo]
            mock_run.side_effect = sp.CalledProcessError(1, "tmux", stderr="session not found")

            with pytest.raises(DispatchError, match="tmux split-window failed"):
                execute_dispatch("testproject", mock_config, name="test-task")
