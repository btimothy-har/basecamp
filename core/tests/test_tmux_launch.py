"""Tests for terminal multiplexer wrapping in launch."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from core.cli.launch import execute_launch
from core.config import Config, ProjectConfig


class TestTerminalWrapping:
    """Tests for automatic terminal multiplexer session wrapping."""

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
            patch("core.cli.launch.validate_dirs", return_value=[non_git_dir]),
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
            patch("core.cli.launch.validate_dirs", return_value=[non_git_dir]),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.dict("os.environ", {"BASECAMP_REPO": "test-repo"}, clear=False),
        ):
            os.environ.pop("TMUX", None)
            os.environ.pop("KITTY_LISTEN_ON", None)

            execute_launch("testproject", config)

            args = mock_execvp.call_args[0][1]
            # Collect all -e values
            e_values = [args[i + 1] for i, a in enumerate(args) if a == "-e"]
            assert "BASECAMP_PROJECT=testproject" in e_values
            assert f"BASECAMP_REPO={non_git_dir.name}" in e_values
            assert any(v.startswith("BASECAMP_SYSTEM_PROMPT=") for v in e_values)

    def test_tmux_forwards_dotenv_vars(self, non_git_dir: Path) -> None:
        """Tmux wrapping should forward vars loaded from .env via -e flags."""
        config = self._make_config(non_git_dir)
        dotenv_file = non_git_dir / ".env"
        dotenv_file.write_text("SECRET_KEY=hunter2\nAPI_URL=https://api.example.com\n")

        env_clean = {k: v for k, v in os.environ.items() if k not in ("TMUX", "KITTY_LISTEN_ON")}
        with (
            patch("core.cli.launch.validate_dirs", return_value=[non_git_dir]),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.dict("os.environ", env_clean, clear=True),
        ):
            execute_launch("testproject", config)

            args = mock_execvp.call_args[0][1]
            e_values = [args[i + 1] for i, a in enumerate(args) if a == "-e"]
            assert "SECRET_KEY=hunter2" in e_values
            assert "API_URL=https://api.example.com" in e_values

    def test_skips_tmux_when_already_in_tmux(self, non_git_dir: Path) -> None:
        """When TMUX is set, should exec claude directly."""
        config = self._make_config(non_git_dir)

        with (
            patch("core.cli.launch.load_dotenv"),
            patch("core.cli.launch.validate_dirs", return_value=[non_git_dir]),
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

        env_no_tmux = {k: v for k, v in os.environ.items() if k != "TMUX"}
        with (
            patch("core.cli.launch.load_dotenv"),
            patch("core.cli.launch.validate_dirs", return_value=[non_git_dir]),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch("shutil.which", return_value=None),
            patch.dict("os.environ", env_no_tmux, clear=True),
        ):
            execute_launch("testproject", config)

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "claude"

    def test_tmux_session_name_uses_project_name(self, non_git_dir: Path) -> None:
        """Tmux session name should be bc-{project_name}."""
        config = self._make_config(non_git_dir)

        env_clean = {k: v for k, v in os.environ.items() if k not in ("TMUX", "KITTY_LISTEN_ON")}
        with (
            patch("core.cli.launch.load_dotenv"),
            patch("core.cli.launch.validate_dirs", return_value=[non_git_dir]),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.dict("os.environ", env_clean, clear=True),
        ):
            execute_launch("testproject", config)

            args = mock_execvp.call_args[0][1]
            session_idx = args.index("-s")
            assert args[session_idx + 1] == "bc-testproject"

    def test_tmux_wrapping_preserves_claude_args(self, non_git_dir: Path) -> None:
        """Claude args (--resume, --plugin-dir, etc.) should pass through in the shell wrapper."""
        config = self._make_config(non_git_dir)

        env_clean = {k: v for k, v in os.environ.items() if k not in ("TMUX", "KITTY_LISTEN_ON")}
        with (
            patch("core.cli.launch.load_dotenv"),
            patch("core.cli.launch.validate_dirs", return_value=[non_git_dir]),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.dict("os.environ", env_clean, clear=True),
        ):
            execute_launch("testproject", config, resume=True)

            args = mock_execvp.call_args[0][1]
            shell_inner = args[-1]
            assert "--resume" in shell_inner

    def test_skips_tmux_when_in_kitty(self, non_git_dir: Path) -> None:
        """When KITTY_LISTEN_ON is set, should exec claude directly (no tmux wrapping)."""
        config = self._make_config(non_git_dir)

        with (
            patch("core.cli.launch.load_dotenv"),
            patch("core.cli.launch.validate_dirs", return_value=[non_git_dir]),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict(
                "os.environ",
                {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123", "BASECAMP_REPO": "test"},
                clear=True,
            ),
            patch("shutil.which", return_value="/usr/bin/tmux"),
        ):
            execute_launch("testproject", config)

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "claude"
