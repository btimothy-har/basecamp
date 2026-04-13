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
    """Tests for the reflect command's session launch."""

    def test_execs_pi_directly(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {}, clear=True),
        ):
            execute_reflect()

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "pi"

    def test_sets_reflect_env_var(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("os.chdir"),
            patch("os.execvp"),
            patch.dict("os.environ", {}, clear=True),
        ):
            execute_reflect()
            assert os.environ["BASECAMP_REFLECT"] == "1"

    def test_chdirs_to_graph(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("os.chdir") as mock_chdir,
            patch("os.execvp"),
            patch.dict("os.environ", {}, clear=True),
        ):
            execute_reflect()
            mock_chdir.assert_called_once_with(graph)

    def test_includes_system_prompt(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {}, clear=True),
        ):
            execute_reflect()

            args = mock_execvp.call_args[0][1]
            assert "--system-prompt" in args
            prompt_idx = args.index("--system-prompt")
            system_prompt = args[prompt_idx + 1]
            assert "Logseq Conventions" in system_prompt

    def test_includes_user_prompt(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {}, clear=True),
        ):
            execute_reflect()

            args = mock_execvp.call_args[0][1]
            separator_idx = args.index("--")
            user_prompt = args[separator_idx + 1]
            assert "Discovery" in user_prompt

    def test_loads_extension(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()
        fake_ext_dir = tmp_path / "extension"
        fake_ext_dir.mkdir()
        (fake_ext_dir / "package.json").write_text("{}")

        with (
            patch("core.cli.reflect.resolve_graph_path", return_value=graph),
            patch("core.cli.reflect.EXTENSION_DIR", fake_ext_dir),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {}, clear=True),
        ):
            execute_reflect()

            args = mock_execvp.call_args[0][1]
            assert "-e" in args
            e_idx = args.index("-e")
            assert args[e_idx + 1] == str(fake_ext_dir)

    def test_not_configured_raises(self) -> None:
        with patch("core.cli.reflect.resolve_graph_path", side_effect=LogseqNotConfiguredError):
            with pytest.raises(LogseqNotConfiguredError):
                execute_reflect()
