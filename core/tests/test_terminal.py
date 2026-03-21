"""Tests for terminal backends."""

from __future__ import annotations

import subprocess as sp
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.exceptions import PaneLaunchError
from core.terminal import (
    DirectBackend,
    KittyBackend,
    TmuxBackend,
    resolve_dispatch_backend,
    resolve_launch_backend,
)


class TestResolveDispatchBackend:
    """Tests for dispatch backend resolution from environment variables."""

    def test_returns_kitty_when_kitty_listen_on_set(self) -> None:
        with patch.dict("os.environ", {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123"}, clear=True):
            backend = resolve_dispatch_backend()
            assert isinstance(backend, KittyBackend)

    def test_returns_tmux_when_tmux_set(self) -> None:
        with patch.dict("os.environ", {"TMUX": "/tmp/tmux-501/default,12345,0"}, clear=True):
            backend = resolve_dispatch_backend()
            assert isinstance(backend, TmuxBackend)

    def test_kitty_takes_priority_over_tmux(self) -> None:
        env = {
            "KITTY_LISTEN_ON": "unix:/tmp/kitty-123",
            "TMUX": "/tmp/tmux-501/default,12345,0",
        }
        with patch.dict("os.environ", env, clear=True):
            backend = resolve_dispatch_backend()
            assert isinstance(backend, KittyBackend)

    def test_returns_none_when_neither_set(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert resolve_dispatch_backend() is None


class TestResolveLaunchBackend:
    """Tests for launch backend resolution."""

    def test_returns_kitty_when_kitty_active(self) -> None:
        with patch.dict("os.environ", {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123"}, clear=True):
            backend = resolve_launch_backend()
            assert isinstance(backend, KittyBackend)

    def test_returns_tmux_when_tmux_active(self) -> None:
        with patch.dict("os.environ", {"TMUX": "/tmp/tmux-501/default,12345,0"}, clear=True):
            backend = resolve_launch_backend()
            assert isinstance(backend, TmuxBackend)
            assert not backend._wrap

    def test_kitty_takes_priority_over_tmux(self) -> None:
        env = {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123", "TMUX": "1"}
        with patch.dict("os.environ", env, clear=True):
            backend = resolve_launch_backend()
            assert isinstance(backend, KittyBackend)

    def test_returns_tmux_wrap_when_tmux_available(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("core.terminal.shutil.which", return_value="/usr/bin/tmux"),
        ):
            backend = resolve_launch_backend()
            assert isinstance(backend, TmuxBackend)
            assert backend._wrap

    def test_returns_direct_when_nothing_available(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("core.terminal.shutil.which", return_value=None),
        ):
            backend = resolve_launch_backend()
            assert isinstance(backend, DirectBackend)


class TestTmuxExecSession:
    """Tests for TmuxBackend.exec_session()."""

    def test_direct_mode_prints_and_execs(self) -> None:
        backend = TmuxBackend(wrap=False)
        with (
            patch("builtins.print") as mock_print,
            patch("os.execvp") as mock_execvp,
        ):
            backend.exec_session(
                ["claude", "--resume"],
                startup_text="header\n",
                env_vars={"FOO": "bar"},
                session_name="bc-test",
            )

            mock_print.assert_called_once_with("header\n", end="")
            mock_execvp.assert_called_once_with("claude", ["claude", "--resume"])

    def test_wrap_mode_creates_tmux_session(self) -> None:
        backend = TmuxBackend(wrap=True)
        with patch("os.execvp") as mock_execvp:
            backend.exec_session(
                ["claude"],
                startup_text="header\n",
                env_vars={"BASECAMP_REPO": "myrepo"},
                session_name="bc-test",
            )

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "tmux"
            args = mock_execvp.call_args[0][1]
            assert args[:2] == ["tmux", "new-session"]
            assert "-s" in args
            assert "bc-test" in args

    def test_wrap_mode_forwards_env_vars(self) -> None:
        backend = TmuxBackend(wrap=True)
        with patch("os.execvp") as mock_execvp:
            backend.exec_session(
                ["claude"],
                startup_text="header\n",
                env_vars={"BASECAMP_REPO": "myrepo", "BASECAMP_PROJECT": "proj"},
                session_name="bc-test",
            )

            args = mock_execvp.call_args[0][1]
            e_values = [args[i + 1] for i, a in enumerate(args) if a == "-e"]
            assert "BASECAMP_REPO=myrepo" in e_values
            assert "BASECAMP_PROJECT=proj" in e_values

    def test_wrap_mode_embeds_header_in_shell(self) -> None:
        backend = TmuxBackend(wrap=True)
        with patch("os.execvp") as mock_execvp:
            backend.exec_session(
                ["claude", "--resume"],
                startup_text="header text",
                env_vars={},
                session_name="bc-test",
            )

            args = mock_execvp.call_args[0][1]
            assert args[-3] == "sh"
            assert args[-2] == "-c"
            shell_inner = args[-1]
            assert "printf %s" in shell_inner
            assert "claude" in shell_inner
            assert "--resume" in shell_inner


class TestKittyExecSession:
    """Tests for KittyBackend.exec_session()."""

    def test_prints_and_execs(self) -> None:
        backend = KittyBackend()
        with (
            patch("builtins.print") as mock_print,
            patch("os.execvp") as mock_execvp,
        ):
            backend.exec_session(
                ["claude", "--resume"],
                startup_text="header\n",
                env_vars={"FOO": "bar"},
                session_name="bc-test",
            )

            mock_print.assert_called_once_with("header\n", end="")
            mock_execvp.assert_called_once_with("claude", ["claude", "--resume"])


class TestDirectExecSession:
    """Tests for DirectBackend.exec_session()."""

    def test_prints_and_execs(self) -> None:
        backend = DirectBackend()
        with (
            patch("builtins.print") as mock_print,
            patch("os.execvp") as mock_execvp,
        ):
            backend.exec_session(
                ["claude"],
                startup_text="header\n",
                env_vars={},
                session_name="bc-test",
            )

            mock_print.assert_called_once_with("header\n", end="")
            mock_execvp.assert_called_once_with("claude", ["claude"])


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
