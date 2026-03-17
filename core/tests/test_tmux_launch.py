"""Tests for tmux wrapping in launch."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from core.cli.launch import execute_launch
from core.config import Config, ProjectConfig


class TestTmuxWrapping:
    """Tests for automatic tmux session wrapping."""

    def _make_config(self, dir_path: Path) -> Config:
        return Config(
            projects={
                "testproject": ProjectConfig(
                    dirs=[str(dir_path)],
                    description="Test project",
                ),
            }
        )

    def test_wraps_in_tmux_when_not_in_tmux(self, non_git_dir: Path) -> None:
        """When TMUX is unset and tmux is available, should exec into tmux."""
        config = self._make_config(non_git_dir)

        with (
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {"BASECAMP_REPO": "test"}, clear=True),
            patch("shutil.which", return_value="/usr/bin/tmux"),
        ):
            execute_launch("testproject", config)

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "tmux"
            args = mock_execvp.call_args[0][1]
            assert args[:2] == ["tmux", "new-session"]
            assert "bc-testproject" in args
            # Claude command is inside the sh -c shell wrapper
            assert args[-3:][0] == "sh"
            assert args[-3:][1] == "-c"
            assert "claude" in args[-1]

    def test_tmux_forwards_basecamp_env_vars(self, non_git_dir: Path) -> None:
        """Tmux wrapping should pass BASECAMP_* env vars via -e flags."""
        config = self._make_config(non_git_dir)

        with (
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.dict("os.environ", {"BASECAMP_REPO": "test-repo"}, clear=False),
        ):
            os.environ.pop("TMUX", None)

            execute_launch("testproject", config)

            args = mock_execvp.call_args[0][1]
            # Collect all -e values
            e_values = [args[i + 1] for i, a in enumerate(args) if a == "-e"]
            assert f"BASECAMP_PROJECT=testproject" in e_values
            assert f"BASECAMP_REPO={non_git_dir.name}" in e_values

    def test_skips_tmux_when_already_in_tmux(self, non_git_dir: Path) -> None:
        """When TMUX is set, should exec claude directly."""
        config = self._make_config(non_git_dir)

        with (
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {"TMUX": "/tmp/tmux-501/default,12345,0"}),
        ):
            execute_launch("testproject", config)

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "claude"

    def test_skips_tmux_when_tmux_not_installed(self, non_git_dir: Path) -> None:
        """When tmux is not installed, should exec claude directly."""
        config = self._make_config(non_git_dir)

        with (
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch("shutil.which", return_value=None),
        ):
            os.environ.pop("TMUX", None)

            execute_launch("testproject", config)

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "claude"

    def test_tmux_session_name_uses_project_name(self, non_git_dir: Path) -> None:
        """Tmux session name should be bc-{project_name}."""
        config = self._make_config(non_git_dir)

        with (
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch("shutil.which", return_value="/usr/bin/tmux"),
        ):
            os.environ.pop("TMUX", None)

            execute_launch("testproject", config)

            args = mock_execvp.call_args[0][1]
            session_idx = args.index("-s")
            assert args[session_idx + 1] == "bc-testproject"

    def test_tmux_wrapping_preserves_claude_args(self, non_git_dir: Path) -> None:
        """Claude args (--resume, --plugin-dir, etc.) should pass through in the shell wrapper."""
        config = self._make_config(non_git_dir)

        with (
            patch("core.cli.launch.load_dotenv"),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch("shutil.which", return_value="/usr/bin/tmux"),
        ):
            os.environ.pop("TMUX", None)

            execute_launch("testproject", config, resume=True)

            args = mock_execvp.call_args[0][1]
            shell_inner = args[-1]
            assert "--resume" in shell_inner
