"""Tests for core.cli.reflect — basecamp reflect command."""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from core.cli.reflect import execute_reflect
from core.exceptions import LogseqNotConfiguredError
from core.prompts.logseq_prompts import load_system_prompt, load_user_prompt

_TEST_DATE = datetime.date(2026, 3, 17)


class TestLogseqPromptLoading:
    """Tests for Logseq prompt loading with user override support."""

    def test_system_prompt_loads_package_default(self) -> None:
        with patch("core.prompts.logseq_prompts.USER_PROMPTS_DIR", Path("/nonexistent")):
            content = load_system_prompt()
        assert "Logseq Conventions" in content
        assert "Constraints" in content

    def test_system_prompt_user_override(self, tmp_path: Path) -> None:
        user_prompt = tmp_path / "logseq.md"
        user_prompt.write_text("Custom logseq system prompt")
        with patch("core.prompts.logseq_prompts.USER_PROMPTS_DIR", tmp_path):
            content = load_system_prompt()
        assert content == "Custom logseq system prompt"

    def test_user_prompt_loads_package_default(self) -> None:
        with patch("core.prompts.logseq_prompts.USER_PROMPTS_DIR", Path("/nonexistent")):
            content = load_user_prompt("reflect", date=_TEST_DATE)
        assert "Discovery" in content
        assert "Proposals" in content

    def test_user_prompt_user_override(self, tmp_path: Path) -> None:
        user_prompt = tmp_path / "reflect.md"
        user_prompt.write_text("Custom reflect prompt")
        with patch("core.prompts.logseq_prompts.USER_PROMPTS_DIR", tmp_path):
            content = load_user_prompt("reflect", date=_TEST_DATE)
        assert content == "Custom reflect prompt"


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
            # Inner sh -c command should invoke claude
            sh_idx = args.index("sh")
            inner_cmd = args[sh_idx + 2]
            assert "claude" in inner_cmd
            # BASECAMP_REFLECT should be passed via tmux -e
            assert "-e" in args
            e_idx = args.index("-e")
            assert args[e_idx + 1] == "BASECAMP_REFLECT=1"

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

    def test_sets_reflect_env_var(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        env: dict[str, str] = {"TMUX": "1"}
        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("core.cli.reflect.is_observer_configured", return_value=True),
            patch("os.chdir"),
            patch("os.execvp"),
            patch.dict("os.environ", env),
        ):
            execute_reflect()
            assert os.environ["BASECAMP_REFLECT"] == "1"

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
            prompt_idx = args.index("--system-prompt")
            system_prompt = args[prompt_idx + 1]
            assert len(system_prompt) > 0
            # Should contain logseq system.md content
            assert "Logseq Conventions" in system_prompt

    def test_includes_user_prompt(self, tmp_path: Path) -> None:
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
            # User prompt is the last arg after --
            separator_idx = args.index("--")
            user_prompt = args[separator_idx + 1]
            assert "Discovery" in user_prompt

    def test_loads_observer_plugin(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()
        # Create fake observer plugin structure so the .exists() check passes
        fake_script_dir = tmp_path / "install"
        plugin_json = fake_script_dir / "plugins" / "observer" / ".claude-plugin" / "plugin.json"
        plugin_json.parent.mkdir(parents=True)
        plugin_json.write_text("{}")

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("core.cli.reflect.is_observer_configured", return_value=True),
            patch("core.cli.reflect.SCRIPT_DIR", fake_script_dir),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {"TMUX": "1"}),
        ):
            execute_reflect()

            args = mock_execvp.call_args[0][1]
            assert "--plugin-dir" in args
            plugin_idx = args.index("--plugin-dir")
            plugin_path = Path(args[plugin_idx + 1])
            assert plugin_path.name == "observer"
            assert plugin_path.parent.name == "plugins"

    def test_does_not_load_companion(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()
        # Create fake observer plugin so --plugin-dir appears in args
        fake_script_dir = tmp_path / "install"
        plugin_json = fake_script_dir / "plugins" / "observer" / ".claude-plugin" / "plugin.json"
        plugin_json.parent.mkdir(parents=True)
        plugin_json.write_text("{}")

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("core.cli.reflect.is_observer_configured", return_value=True),
            patch("core.cli.reflect.SCRIPT_DIR", fake_script_dir),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {"TMUX": "1"}),
        ):
            execute_reflect()

            args = mock_execvp.call_args[0][1]
            plugin_dirs = [args[i + 1] for i, arg in enumerate(args) if arg == "--plugin-dir"]
            assert all(Path(d).name != "companion" for d in plugin_dirs)

    def test_not_configured_raises(self) -> None:
        with patch("core.cli.reflect.resolve_graph_path", side_effect=LogseqNotConfiguredError):
            with pytest.raises(LogseqNotConfiguredError):
                execute_reflect()

    def test_skips_tmux_when_tmux_not_installed(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        env = os.environ.copy()
        env.pop("TMUX", None)

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("core.cli.reflect.is_observer_configured", return_value=True),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch("shutil.which", return_value=None),
            patch.dict("os.environ", env, clear=True),
        ):
            execute_reflect()

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "claude"

    def test_skips_tmux_when_in_kitty(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("core.cli.reflect.is_observer_configured", return_value=True),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {"KITTY_LISTEN_ON": "unix:/tmp/kitty-123"}, clear=True),
            patch("shutil.which", return_value="/usr/bin/tmux"),
        ):
            execute_reflect()

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "claude"
