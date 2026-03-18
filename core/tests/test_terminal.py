"""Tests for terminal multiplexer backends."""

from __future__ import annotations

import subprocess as sp
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.exceptions import PaneLaunchError
from core.terminal import KittyBackend, TmuxBackend, detect_backend, in_multiplexer


class TestDetectBackend:
    """Tests for backend detection from environment variables."""

    def test_returns_kitty_when_kitty_listen_on_set(self) -> None:
        with patch.dict("os.environ", {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123"}, clear=True):
            backend = detect_backend()
            assert isinstance(backend, KittyBackend)

    def test_returns_tmux_when_tmux_set(self) -> None:
        with patch.dict("os.environ", {"TMUX": "/tmp/tmux-501/default,12345,0"}, clear=True):
            backend = detect_backend()
            assert isinstance(backend, TmuxBackend)

    def test_kitty_takes_priority_over_tmux(self) -> None:
        env = {
            "KITTY_LISTEN_ON": "unix:/tmp/kitty-123",
            "TMUX": "/tmp/tmux-501/default,12345,0",
        }
        with patch.dict("os.environ", env, clear=True):
            backend = detect_backend()
            assert isinstance(backend, KittyBackend)

    def test_returns_none_when_neither_set(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert detect_backend() is None


class TestInMultiplexer:
    """Tests for in_multiplexer() detection."""

    def test_true_when_kitty(self) -> None:
        with patch.dict("os.environ", {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123"}, clear=True):
            assert in_multiplexer() is True

    def test_true_when_tmux(self) -> None:
        with patch.dict("os.environ", {"TMUX": "/tmp/tmux-501/default,12345,0"}, clear=True):
            assert in_multiplexer() is True

    def test_true_when_both(self) -> None:
        env = {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123", "TMUX": "1"}
        with patch.dict("os.environ", env, clear=True):
            assert in_multiplexer() is True

    def test_false_when_neither(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert in_multiplexer() is False


class TestTmuxBackend:
    """Tests for tmux split-window pane spawning."""

    def test_spawn_pane_builds_correct_command(self) -> None:
        mock_run = MagicMock()
        mock_run.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="%42\n", stderr="")

        with patch("core.terminal.subprocess.run", mock_run):
            TmuxBackend().spawn_pane(
                Path("/tmp/launch.sh"),
                env={"MY_VAR": "hello"},
                cwd=Path("/tmp/work"),
                title="test-task",
            )

        split_call = mock_run.call_args_list[0]
        cmd = split_call[0][0]
        assert cmd[0] == "tmux"
        assert "split-window" in cmd
        assert "-v" in cmd

    def test_spawn_pane_passes_env_vars(self) -> None:
        mock_run = MagicMock()
        mock_run.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="%42\n", stderr="")

        with patch("core.terminal.subprocess.run", mock_run):
            TmuxBackend().spawn_pane(
                Path("/tmp/launch.sh"),
                env={"TASK_DIR": "/tmp/task", "REPO": "myrepo"},
                cwd=Path("/tmp"),
                title="t",
            )

        cmd = mock_run.call_args_list[0][0][0]
        cmd_str = " ".join(str(c) for c in cmd)
        assert "TASK_DIR=/tmp/task" in cmd_str
        assert "REPO=myrepo" in cmd_str

    def test_spawn_pane_sets_cwd(self) -> None:
        mock_run = MagicMock()
        mock_run.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="%42\n", stderr="")

        with patch("core.terminal.subprocess.run", mock_run):
            TmuxBackend().spawn_pane(
                Path("/tmp/launch.sh"),
                env={},
                cwd=Path("/my/project"),
                title="t",
            )

        cmd = mock_run.call_args_list[0][0][0]
        c_idx = cmd.index("-c")
        assert cmd[c_idx + 1] == "/my/project"

    def test_spawn_pane_sets_title(self) -> None:
        mock_run = MagicMock()
        mock_run.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="%42\n", stderr="")

        with patch("core.terminal.subprocess.run", mock_run):
            TmuxBackend().spawn_pane(
                Path("/tmp/launch.sh"),
                env={},
                cwd=Path("/tmp"),
                title="my-task",
            )

        # Second call should be select-pane for title
        title_call = mock_run.call_args_list[1]
        cmd = title_call[0][0]
        assert cmd[0] == "tmux"
        assert "select-pane" in cmd
        assert "%42" in cmd
        assert "my-task" in cmd

    def test_spawn_pane_raises_on_failure(self) -> None:
        with patch("core.terminal.subprocess.run") as mock_run:
            mock_run.side_effect = sp.CalledProcessError(1, "tmux", stderr="session not found")

            with pytest.raises(PaneLaunchError, match="tmux pane launch failed"):
                TmuxBackend().spawn_pane(Path("/tmp/launch.sh"), env={}, cwd=Path("/tmp"), title="t")


class TestKittyBackend:
    """Tests for Kitty remote control pane spawning."""

    def test_spawn_pane_builds_correct_command(self) -> None:
        mock_run = MagicMock()
        mock_run.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with (
            patch("core.terminal.subprocess.run", mock_run),
            patch.dict("os.environ", {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123"}),
        ):
            KittyBackend().spawn_pane(
                Path("/tmp/launch.sh"),
                env={},
                cwd=Path("/tmp"),
                title="test-task",
            )

        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["kitty", "@", "--to"]
        assert cmd[3] == "unix:/tmp/kitty-123"
        assert "launch" in cmd
        assert "--type=window" in cmd

    def test_spawn_pane_uses_keep_focus(self) -> None:
        mock_run = MagicMock()
        mock_run.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with (
            patch("core.terminal.subprocess.run", mock_run),
            patch.dict("os.environ", {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123"}),
        ):
            KittyBackend().spawn_pane(Path("/tmp/launch.sh"), env={}, cwd=Path("/tmp"), title="t")

        cmd = mock_run.call_args[0][0]
        assert "--keep-focus" in cmd

    def test_spawn_pane_passes_env_vars(self) -> None:
        mock_run = MagicMock()
        mock_run.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with (
            patch("core.terminal.subprocess.run", mock_run),
            patch.dict("os.environ", {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123"}),
        ):
            KittyBackend().spawn_pane(
                Path("/tmp/launch.sh"),
                env={"TASK_DIR": "/tmp/task", "REPO": "myrepo"},
                cwd=Path("/tmp"),
                title="t",
            )

        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(str(c) for c in cmd)
        assert "--env TASK_DIR=/tmp/task" in cmd_str
        assert "--env REPO=myrepo" in cmd_str

    def test_spawn_pane_sets_cwd(self) -> None:
        mock_run = MagicMock()
        mock_run.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with (
            patch("core.terminal.subprocess.run", mock_run),
            patch.dict("os.environ", {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123"}),
        ):
            KittyBackend().spawn_pane(Path("/tmp/launch.sh"), env={}, cwd=Path("/my/project"), title="t")

        cmd = mock_run.call_args[0][0]
        cwd_idx = cmd.index("--cwd")
        assert cmd[cwd_idx + 1] == "/my/project"

    def test_spawn_pane_sets_title(self) -> None:
        mock_run = MagicMock()
        mock_run.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with (
            patch("core.terminal.subprocess.run", mock_run),
            patch.dict("os.environ", {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123"}),
        ):
            KittyBackend().spawn_pane(Path("/tmp/launch.sh"), env={}, cwd=Path("/tmp"), title="my-task")

        cmd = mock_run.call_args[0][0]
        title_idx = cmd.index("--title")
        assert cmd[title_idx + 1] == "my-task"

    def test_spawn_pane_appends_script(self) -> None:
        mock_run = MagicMock()
        mock_run.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with (
            patch("core.terminal.subprocess.run", mock_run),
            patch.dict("os.environ", {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123"}),
        ):
            KittyBackend().spawn_pane(Path("/tmp/launch.sh"), env={}, cwd=Path("/tmp"), title="t")

        cmd = mock_run.call_args[0][0]
        assert cmd[-1] == "/tmp/launch.sh"

    def test_spawn_pane_raises_on_failure(self) -> None:
        with (
            patch("core.terminal.subprocess.run") as mock_run,
            patch.dict("os.environ", {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123"}),
        ):
            mock_run.side_effect = sp.CalledProcessError(1, "kitty", stderr="remote control disabled")

            with pytest.raises(PaneLaunchError, match="kitty pane launch failed"):
                KittyBackend().spawn_pane(Path("/tmp/launch.sh"), env={}, cwd=Path("/tmp"), title="t")
