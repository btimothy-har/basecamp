"""Tests for core.cli.plan — basecamp plan command."""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from core.cli.plan import execute_plan
from core.exceptions import LogseqNotConfiguredError
from core.prompts.logseq_prompts import load_user_prompt

_TEST_DATE = datetime.date(2026, 3, 17)


class TestPlanUserPrompt:
    """Tests for the plan user prompt loading."""

    def test_loads_package_default(self) -> None:
        with patch("core.prompts.logseq_prompts.USER_PROMPTS_DIR", Path("/nonexistent")):
            content = load_user_prompt("plan", date=_TEST_DATE)
        assert "Review" in content
        assert "Priorities" in content

    def test_user_override(self, tmp_path: Path) -> None:
        user_prompt = tmp_path / "plan.md"
        user_prompt.write_text("Custom plan prompt")
        with patch("core.prompts.logseq_prompts.USER_PROMPTS_DIR", tmp_path):
            content = load_user_prompt("plan", date=_TEST_DATE)
        assert content == "Custom plan prompt"


class TestPlanLaunch:
    """Tests for the plan command's session launch."""

    def test_execs_pi_directly(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.plan.resolve_graph_path", return_value=graph),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {}, clear=True),
        ):
            execute_plan()

            mock_execvp.assert_called_once()
            assert mock_execvp.call_args[0][0] == "pi"

    def test_sets_reflect_env_var(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.plan.resolve_graph_path", return_value=graph),
            patch("os.chdir"),
            patch("os.execvp"),
            patch.dict("os.environ", {}, clear=True),
        ):
            execute_plan()
            assert os.environ["BASECAMP_REFLECT"] == "1"

    def test_chdirs_to_graph(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.plan.resolve_graph_path", return_value=graph),
            patch("os.chdir") as mock_chdir,
            patch("os.execvp"),
            patch.dict("os.environ", {}, clear=True),
        ):
            execute_plan()
            mock_chdir.assert_called_once_with(graph)

    def test_includes_system_prompt(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.plan.resolve_graph_path", return_value=graph),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {}, clear=True),
        ):
            execute_plan()

            args = mock_execvp.call_args[0][1]
            assert "--system-prompt" in args
            prompt_idx = args.index("--system-prompt")
            system_prompt = args[prompt_idx + 1]
            assert "Logseq Conventions" in system_prompt

    def test_includes_user_prompt(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with (
            patch("core.cli.plan.resolve_graph_path", return_value=graph),
            patch("os.chdir"),
            patch("os.execvp") as mock_execvp,
            patch.dict("os.environ", {}, clear=True),
        ):
            execute_plan()

            args = mock_execvp.call_args[0][1]
            separator_idx = args.index("--")
            user_prompt = args[separator_idx + 1]
            assert "Priorities" in user_prompt

    def test_not_configured_raises(self) -> None:
        with patch("core.cli.plan.resolve_graph_path", side_effect=LogseqNotConfiguredError):
            with pytest.raises(LogseqNotConfiguredError):
                execute_plan()
