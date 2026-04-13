"""Tests for launch with terminal backends."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from core.cli.launch import execute_launch
from core.config import Config, ProjectConfig


class TestLaunchTerminalBackend:
    """Tests for launch exec_session behavior across terminal backends."""

    def _make_config(self, dir_path: Path) -> Config:
        return Config(
            projects={
                "testproject": ProjectConfig(
                    dirs=[str(dir_path)],
                    description="Test project",
                ),
            }
        )

    def test_execs_pi_directly(self, non_git_dir: Path) -> None:
        """Should always exec pi directly (no tmux wrapping)."""
        config = self._make_config(non_git_dir)

        with (
            patch("core.cli.launch.validate_dirs", return_value=[non_git_dir]),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {}, clear=True),
        ):
            execute_launch("testproject", config)

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "pi"

    def test_exports_env_vars_before_exec(self, non_git_dir: Path) -> None:
        """Env vars should be exported to os.environ before execvp."""
        config = self._make_config(non_git_dir)

        captured_env: dict[str, str] = {}

        def fake_execvp(program, args):
            captured_env.update({k: v for k, v in os.environ.items() if k.startswith("BASECAMP_")})

        with (
            patch("core.cli.launch.validate_dirs", return_value=[non_git_dir]),
            patch("os.chdir"),
            patch("os.execvp", side_effect=fake_execvp),
            patch.dict("os.environ", {}, clear=True),
        ):
            execute_launch("testproject", config)

        assert captured_env["BASECAMP_PROJECT"] == "testproject"
        assert captured_env["BASECAMP_REPO"] == non_git_dir.name

    def test_execs_pi_when_in_tmux(self, non_git_dir: Path) -> None:
        """When TMUX is set, should still exec pi directly."""
        config = self._make_config(non_git_dir)

        with (
            patch("core.cli.launch.validate_dirs", return_value=[non_git_dir]),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {"TMUX": "/tmp/tmux-501/default,12345,0"}),
        ):
            execute_launch("testproject", config)

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "pi"

    def test_execs_pi_when_in_kitty(self, non_git_dir: Path) -> None:
        """When KITTY_LISTEN_ON is set, should exec pi directly."""
        config = self._make_config(non_git_dir)

        with (
            patch("core.cli.launch.validate_dirs", return_value=[non_git_dir]),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict(
                "os.environ",
                {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123"},
                clear=True,
            ),
        ):
            execute_launch("testproject", config)

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "pi"

    def test_preserves_extra_args(self, non_git_dir: Path) -> None:
        """Extra args should pass through to pi command."""
        config = self._make_config(non_git_dir)

        with (
            patch("core.cli.launch.validate_dirs", return_value=[non_git_dir]),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {}, clear=True),
        ):
            execute_launch("testproject", config, extra_args=["--resume"])

            cmd = mock_execvp.call_args[0][1]
            assert "--resume" in cmd
