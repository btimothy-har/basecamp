"""Tests for shell completion functions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click import Context, Parameter
from core.cli.completions import complete_project_name, complete_worktree_name
from core.config import Config, ProjectConfig
from core.git import WorktreeInfo


@pytest.fixture
def mock_ctx() -> Context:
    ctx = MagicMock(spec=Context)
    ctx.params = {}
    return ctx


@pytest.fixture
def mock_param() -> Parameter:
    return MagicMock(spec=Parameter)


@pytest.fixture
def sample_config() -> Config:
    return Config(
        projects={
            "alpha": ProjectConfig(dirs=["GitHub/alpha"]),
            "beta": ProjectConfig(dirs=["GitHub/beta"]),
            "gamma": ProjectConfig(dirs=["GitHub/gamma"]),
        }
    )


class TestCompleteProjectName:
    def test_returns_all_on_empty_prefix(self, mock_ctx: Context, mock_param: Parameter, sample_config: Config) -> None:
        with patch("core.cli.completions.load_config", return_value=sample_config):
            items = complete_project_name(mock_ctx, mock_param, "")
        assert [i.value for i in items] == ["alpha", "beta", "gamma"]

    def test_filters_by_prefix(self, mock_ctx: Context, mock_param: Parameter, sample_config: Config) -> None:
        with patch("core.cli.completions.load_config", return_value=sample_config):
            items = complete_project_name(mock_ctx, mock_param, "al")
        assert [i.value for i in items] == ["alpha"]

    def test_no_match_returns_empty(self, mock_ctx: Context, mock_param: Parameter, sample_config: Config) -> None:
        with patch("core.cli.completions.load_config", return_value=sample_config):
            items = complete_project_name(mock_ctx, mock_param, "zzz")
        assert items == []

    def test_config_error_returns_empty(self, mock_ctx: Context, mock_param: Parameter) -> None:
        with patch("core.cli.completions.load_config", side_effect=RuntimeError("bad")):
            items = complete_project_name(mock_ctx, mock_param, "")
        assert items == []


class TestCompleteWorktreeName:
    def test_no_project_param_returns_empty(self, mock_ctx: Context, mock_param: Parameter) -> None:
        mock_ctx.params = {}
        items = complete_worktree_name(mock_ctx, mock_param, "")
        assert items == []

    def test_returns_worktree_names(self, mock_ctx: Context, mock_param: Parameter, sample_config: Config) -> None:
        now = datetime.now(tz=timezone.utc)
        mock_ctx.params = {"project": "alpha"}
        worktrees = [
            WorktreeInfo(
                name="auth",
                path=Path("/fake/auth"),
                branch="wt/auth",
                created_at=now,
                project="alpha",
                repo_name="alpha",
            ),
            WorktreeInfo(
                name="api",
                path=Path("/fake/api"),
                branch="wt/api",
                created_at=now,
                project="alpha",
                repo_name="alpha",
            ),
        ]
        with (
            patch("core.cli.completions.load_config", return_value=sample_config),
            patch("core.cli.completions.resolve_project", return_value=sample_config.projects["alpha"]),
            patch("core.cli.completions.validate_dirs", return_value=[MagicMock()]),
            patch("core.cli.completions.resolve_repo_name", return_value="alpha"),
            patch("core.cli.completions.list_worktrees", return_value=worktrees),
        ):
            items = complete_worktree_name(mock_ctx, mock_param, "a")
        assert [i.value for i in items] == ["auth", "api"]

    def test_error_returns_empty(self, mock_ctx: Context, mock_param: Parameter) -> None:
        mock_ctx.params = {"project": "nonexistent"}
        with patch("core.cli.completions.load_config", side_effect=RuntimeError("bad")):
            items = complete_worktree_name(mock_ctx, mock_param, "")
        assert items == []
