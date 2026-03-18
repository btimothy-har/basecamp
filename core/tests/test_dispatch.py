"""Tests for dispatch command."""

from __future__ import annotations

import subprocess as sp
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.cli.dispatch import execute_dispatch
from core.exceptions import DispatchError, InvalidTaskNameError, NoMultiplexerError, TasksDirNotSetError


def _tmux_env(tasks_dir: Path) -> dict[str, str]:
    """Minimal env vars for a valid dispatch call via tmux."""
    return {
        "TMUX": "/tmp/tmux-1000/default,12345,0",
        "CLAUDE_SESSION_ID": "test-session-123",
        "BASECAMP_TASKS_DIR": str(tasks_dir),
        "BASECAMP_REPO": "test-repo",
    }


def _kitty_env(tasks_dir: Path) -> dict[str, str]:
    """Minimal env vars for a valid dispatch call via Kitty."""
    return {
        "KITTY_LISTEN_ON": "unix:/tmp/kitty-123",
        "CLAUDE_SESSION_ID": "test-session-123",
        "BASECAMP_TASKS_DIR": str(tasks_dir),
        "BASECAMP_REPO": "test-repo",
    }


def _mock_subprocess_run() -> MagicMock:
    """Create a subprocess.run mock that succeeds (tmux returns pane ID)."""
    mock = MagicMock()
    mock.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="%42\n", stderr="")
    return mock


class TestExecuteDispatchValidation:
    """Tests for dispatch validation logic."""

    def test_raises_no_multiplexer(self, tmp_path: Path) -> None:
        env = {"CLAUDE_SESSION_ID": "test-session-123", "BASECAMP_TASKS_DIR": str(tmp_path)}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(NoMultiplexerError):
                execute_dispatch(name="test-task")

    def test_raises_no_session_id(self, tmp_path: Path) -> None:
        env = {"TMUX": "/tmp/tmux-1000/default,12345,0", "BASECAMP_TASKS_DIR": str(tmp_path)}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(DispatchError, match="CLAUDE_SESSION_ID"):
                execute_dispatch(name="test-task")

    def test_raises_no_tasks_dir(self) -> None:
        env = {"TMUX": "/tmp/tmux-1000/default,12345,0", "CLAUDE_SESSION_ID": "test-session-123"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(TasksDirNotSetError):
                execute_dispatch(name="test-task")

    @pytest.mark.parametrize(
        "bad_name",
        ["../escape", "/absolute/path", "has/slash", ".dotstart", "has spaces", "semi;colon"],
    )
    def test_raises_invalid_task_name(self, bad_name: str, tmp_path: Path) -> None:
        env = _tmux_env(tmp_path)
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(InvalidTaskNameError):
                execute_dispatch(name=bad_name)


class TestExecuteDispatchLauncher:
    """Tests for launcher script generation."""

    def test_launcher_with_prompt(self, tmp_path: Path) -> None:
        task = tmp_path / "test-task"
        task.mkdir()
        (task / "prompt.md").write_text("Do the thing")

        mock_run = _mock_subprocess_run()
        env = _tmux_env(tmp_path)
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.cli.dispatch.time.sleep"),
        ):
            execute_dispatch(name="test-task")

            script = (task / "launch.sh").read_text()
            assert '-- "$(cat' in script
            assert "prompt.md" in script

    def test_launcher_bare_worker(self, tmp_path: Path) -> None:
        mock_run = _mock_subprocess_run()
        env = _tmux_env(tmp_path)
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.cli.dispatch.time.sleep"),
        ):
            execute_dispatch(name="bare-task")

            script = (tmp_path / "bare-task" / "launch.sh").read_text()
            assert '-- "$(cat' not in script
            assert "prompt.md" not in script

    def test_launcher_with_system_prompt(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "assembled" / "myproject.md"
        prompt_file.parent.mkdir()
        prompt_file.write_text("You are a helpful assistant")

        mock_run = _mock_subprocess_run()
        env = {**_tmux_env(tmp_path), "BASECAMP_SYSTEM_PROMPT": str(prompt_file)}
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.cli.dispatch.time.sleep"),
        ):
            execute_dispatch(name="test-task")

            script = (tmp_path / "test-task" / "launch.sh").read_text()
            assert "--system-prompt" in script
            assert "myproject.md" in script

    def test_launcher_default_model(self, tmp_path: Path) -> None:
        mock_run = _mock_subprocess_run()
        env = _tmux_env(tmp_path)
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.cli.dispatch.time.sleep"),
        ):
            execute_dispatch(name="test-task")

            script = (tmp_path / "test-task" / "launch.sh").read_text()
            assert "--model sonnet" in script

    def test_launcher_custom_model(self, tmp_path: Path) -> None:
        mock_run = _mock_subprocess_run()
        env = _tmux_env(tmp_path)
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.cli.dispatch.time.sleep"),
        ):
            execute_dispatch(name="test-task", model="opus")

            script = (tmp_path / "test-task" / "launch.sh").read_text()
            assert "--model opus" in script


class TestExecuteDispatchTmux:
    """Tests for tmux pane management."""

    def test_tmux_env_vars_passed(self, tmp_path: Path) -> None:
        mock_run = _mock_subprocess_run()
        env = _tmux_env(tmp_path)
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.cli.dispatch.time.sleep"),
        ):
            execute_dispatch(name="test-task")

            split_call = mock_run.call_args_list[0]
            cmd = split_call[0][0]
            cmd_str = " ".join(str(c) for c in cmd)
            assert "BASECAMP_TASK_DIR=" in cmd_str
            assert "BASECAMP_REPO=test-repo" in cmd_str

    def test_tmux_sets_pane_title(self, tmp_path: Path) -> None:
        mock_run = _mock_subprocess_run()
        env = _tmux_env(tmp_path)
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.cli.dispatch.time.sleep"),
        ):
            execute_dispatch(name="test-task")

            title_call = mock_run.call_args_list[1]
            cmd = title_call[0][0]
            assert cmd[0] == "tmux"
            assert "select-pane" in cmd
            assert "%42" in cmd
            assert "test-task" in cmd

    def test_tmux_cwd_is_current_dir(self, tmp_path: Path) -> None:
        mock_run = _mock_subprocess_run()
        env = _tmux_env(tmp_path)
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.cli.dispatch.time.sleep"),
        ):
            execute_dispatch(name="test-task")

            split_call = mock_run.call_args_list[0]
            cmd = split_call[0][0]
            c_idx = cmd.index("-c")
            assert cmd[c_idx + 1] == str(Path.cwd())

    def test_stale_session_id_removed(self, tmp_path: Path) -> None:
        task = tmp_path / "reused-task"
        task.mkdir()
        (task / "session_id").write_text("old-session-abc")

        mock_run = _mock_subprocess_run()
        env = _tmux_env(tmp_path)
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.cli.dispatch.time.sleep"),
        ):
            execute_dispatch(name="reused-task")

            assert not (task / "session_id").exists()

    def test_tmux_failure_raises(self, tmp_path: Path) -> None:
        env = _tmux_env(tmp_path)
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.terminal.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = sp.CalledProcessError(1, "tmux", stderr="session not found")

            with pytest.raises(DispatchError, match="tmux pane launch failed"):
                execute_dispatch(name="test-task")


class TestExecuteDispatchKitty:
    """Tests for Kitty pane management."""

    def test_kitty_env_vars_passed(self, tmp_path: Path) -> None:
        mock_run = _mock_subprocess_run()
        env = _kitty_env(tmp_path)
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.cli.dispatch.time.sleep"),
        ):
            execute_dispatch(name="test-task")

            cmd = mock_run.call_args[0][0]
            cmd_str = " ".join(str(c) for c in cmd)
            assert "--env BASECAMP_TASK_DIR=" in cmd_str
            assert "--env BASECAMP_REPO=test-repo" in cmd_str

    def test_kitty_uses_socket(self, tmp_path: Path) -> None:
        mock_run = _mock_subprocess_run()
        env = _kitty_env(tmp_path)
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.cli.dispatch.time.sleep"),
        ):
            execute_dispatch(name="test-task")

            cmd = mock_run.call_args[0][0]
            assert cmd[:3] == ["kitty", "@", "--to"]
            assert cmd[3] == "unix:/tmp/kitty-123"

    def test_kitty_preferred_over_tmux(self, tmp_path: Path) -> None:
        mock_run = _mock_subprocess_run()
        env = {**_kitty_env(tmp_path), "TMUX": "/tmp/tmux-501/default,12345,0"}
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.cli.dispatch.time.sleep"),
        ):
            execute_dispatch(name="test-task")

            cmd = mock_run.call_args[0][0]
            assert cmd[0] == "kitty"

    def test_kitty_failure_raises(self, tmp_path: Path) -> None:
        env = _kitty_env(tmp_path)
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.terminal.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = sp.CalledProcessError(1, "kitty", stderr="remote control disabled")

            with pytest.raises(DispatchError, match="kitty pane launch failed"):
                execute_dispatch(name="test-task")


class TestExecuteDispatchNameGeneration:
    """Tests for auto-generated task names."""

    def test_auto_generates_name(self, tmp_path: Path) -> None:
        mock_run = _mock_subprocess_run()
        env = _tmux_env(tmp_path)
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.cli.dispatch.time.sleep"),
        ):
            execute_dispatch()

            dirs = list(tmp_path.iterdir())
            assert len(dirs) == 1
            assert dirs[0].name.startswith("worker-")
            assert len(dirs[0].name) == len("worker-") + 8
