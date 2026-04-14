"""Tests for terminal backends."""

from __future__ import annotations

from unittest.mock import patch

from core.terminal import (
    KittyBackend,
    TerminalBackend,
    TmuxBackend,
    resolve_launch_backend,
)


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

    def test_kitty_takes_priority_over_tmux(self) -> None:
        env = {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123", "TMUX": "1"}
        with patch.dict("os.environ", env, clear=True):
            backend = resolve_launch_backend()
            assert isinstance(backend, KittyBackend)

    def test_returns_base_when_nothing_available(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            backend = resolve_launch_backend()
            assert type(backend) is TerminalBackend


class TestExecSession:
    """Tests for TerminalBackend.exec_session()."""

    def test_exports_env_vars_and_execs(self) -> None:
        backend = TerminalBackend()
        with (
            patch("builtins.print") as mock_print,
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {}, clear=True),
        ):
            backend.exec_session(
                ["pi", "--resume"],
                startup_text="header\n",
                env_vars={"BASECAMP_REPO": "myrepo"},
                session_name="bc-test",
            )

            import os

            assert os.environ["BASECAMP_REPO"] == "myrepo"
            mock_print.assert_called_once_with("header\n", end="")
            mock_execvp.assert_called_once_with("pi", ["pi", "--resume"])

    def test_tmux_backend_inherits_exec_session(self) -> None:
        """TmuxBackend uses the same exec_session as base (no wrapping)."""
        backend = TmuxBackend()
        with (
            patch("builtins.print") as mock_print,
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {}, clear=True),
        ):
            backend.exec_session(
                ["pi"],
                startup_text="header\n",
                env_vars={"FOO": "bar"},
                session_name="bc-test",
            )

            mock_print.assert_called_once_with("header\n", end="")
            mock_execvp.assert_called_once_with("pi", ["pi"])

    def test_kitty_backend_inherits_exec_session(self) -> None:
        backend = KittyBackend()
        with (
            patch("builtins.print") as mock_print,
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {}, clear=True),
        ):
            backend.exec_session(
                ["pi"],
                startup_text="header\n",
                env_vars={},
                session_name="bc-test",
            )

            mock_print.assert_called_once_with("header\n", end="")
            mock_execvp.assert_called_once_with("pi", ["pi"])
