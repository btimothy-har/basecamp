"""Tests for core.cli.reflect — basecamp reflect command."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from core.cli.reflect import execute_reflect
from core.exceptions import LogseqNotConfiguredError


class TestReflectLaunch:
    """Tests for the reflect command's Claude session launch."""

    def test_wraps_in_tmux_when_not_in_tmux(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("core.cli.reflect.is_observer_configured", return_value=True),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {}, clear=True),
            patch("shutil.which", return_value="/usr/bin/tmux"),
        ):
            execute_reflect()

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "tmux"
            args = mock_execvp.call_args[0][1]
            assert args[:2] == ["tmux", "new-session"]

    def test_tmux_session_name_is_bc_reflect(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("core.cli.reflect.is_observer_configured", return_value=True),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {}, clear=True),
            patch("shutil.which", return_value="/usr/bin/tmux"),
        ):
            execute_reflect()

            args = mock_execvp.call_args[0][1]
            session_idx = args.index("-s")
            assert args[session_idx + 1] == "bc-reflect"

    def test_skips_tmux_when_already_in_tmux(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("core.cli.reflect.is_observer_configured", return_value=True),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {"TMUX": "/tmp/tmux-501/default,12345,0"}),
        ):
            execute_reflect()

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "claude"

    def test_chdirs_to_graph(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("core.cli.reflect.is_observer_configured", return_value=True),
            patch("os.chdir") as mock_chdir,
            patch("os.execvp"),
            patch.dict("os.environ", {"TMUX": "1"}),
        ):
            execute_reflect()
            mock_chdir.assert_called_once_with(graph)

    def test_includes_system_prompt(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("core.cli.reflect.is_observer_configured", return_value=True),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {"TMUX": "1"}),
        ):
            execute_reflect()

            args = mock_execvp.call_args[0][1]
            assert "--system-prompt" in args

    def test_loads_observer_plugin(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("core.cli.reflect.is_observer_configured", return_value=True),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {"TMUX": "1"}),
        ):
            execute_reflect()

            args = mock_execvp.call_args[0][1]
            assert "--plugin-dir" in args
            plugin_idx = args.index("--plugin-dir")
            assert "observer" in args[plugin_idx + 1]

    def test_does_not_load_companion(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("core.cli.reflect.is_observer_configured", return_value=True),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {"TMUX": "1"}),
        ):
            execute_reflect()

            args = mock_execvp.call_args[0][1]
            for i, arg in enumerate(args):
                if arg == "--plugin-dir":
                    assert "companion" not in args[i + 1]

    def test_not_configured_raises(self) -> None:
        with patch("core.cli.reflect.resolve_graph_path", side_effect=LogseqNotConfiguredError):
            with pytest.raises(LogseqNotConfiguredError):
                execute_reflect()

    def test_skips_tmux_when_tmux_not_installed(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("core.cli.reflect.is_observer_configured", return_value=True),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch("shutil.which", return_value=None),
        ):
            os.environ.pop("TMUX", None)
            execute_reflect()

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "claude"
