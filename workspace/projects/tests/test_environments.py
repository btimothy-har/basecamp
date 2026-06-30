"""Tests for basecamp-workspace per-repo environment configuration."""

from __future__ import annotations

import json
from pathlib import Path

import basecamp_workspace.environments as environments
import pytest
from basecamp_core.settings import CONFIG_VERSION, Settings
from basecamp_workspace.environments import EnvironmentConfig
from pydantic import ValidationError


@pytest.fixture
def cfg(tmp_path: Path) -> Settings:
    """Return a Settings instance backed by a temp config file."""
    return Settings(tmp_path / "config.json")


class TestEnvironmentSchema:
    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            EnvironmentConfig(setup="uv sync", maintenance="x")


class TestLoadGet:
    def test_load_empty_when_missing(self, cfg: Settings) -> None:
        assert environments.load_environments(cfg) == {}

    def test_get_missing_repo_is_none(self, cfg: Settings) -> None:
        assert environments.get_environment("nope", cfg) is None

    def test_load_returns_models(self, cfg: Settings) -> None:
        cfg._write({"environments": {"basecamp": {"setup": "uv sync"}}})

        loaded = environments.load_environments(cfg)

        assert loaded["basecamp"] == EnvironmentConfig(setup="uv sync")


class TestSetRemove:
    def test_set_then_get_round_trip(self, cfg: Settings) -> None:
        environments.set_environment("basecamp", EnvironmentConfig(setup="uv sync && npm ci"), cfg)

        assert environments.get_environment("basecamp", cfg) == EnvironmentConfig(setup="uv sync && npm ci")

    def test_set_persists_nested_shape_and_version(self, cfg: Settings) -> None:
        environments.set_environment("basecamp", EnvironmentConfig(setup="uv sync"), cfg)

        data = json.loads(cfg.path.read_text())
        assert data["version"] == CONFIG_VERSION
        assert data["environments"]["basecamp"] == {"setup": "uv sync"}

    def test_set_strips_command(self, cfg: Settings) -> None:
        environments.set_environment("basecamp", EnvironmentConfig(setup="  uv sync  "), cfg)

        assert environments.get_environment("basecamp", cfg) == EnvironmentConfig(setup="uv sync")

    def test_set_blank_command_clears_entry(self, cfg: Settings) -> None:
        environments.set_environment("basecamp", EnvironmentConfig(setup="uv sync"), cfg)

        environments.set_environment("basecamp", EnvironmentConfig(setup="   "), cfg)

        assert environments.get_environment("basecamp", cfg) is None
        assert "basecamp" not in cfg.get_section("environments")

    def test_set_is_per_repo(self, cfg: Settings) -> None:
        environments.set_environment("alpha", EnvironmentConfig(setup="uv sync"), cfg)
        environments.set_environment("beta", EnvironmentConfig(setup="npm ci"), cfg)

        assert environments.get_environment("alpha", cfg) == EnvironmentConfig(setup="uv sync")
        assert environments.get_environment("beta", cfg) == EnvironmentConfig(setup="npm ci")

    def test_remove_entry(self, cfg: Settings) -> None:
        environments.set_environment("basecamp", EnvironmentConfig(setup="uv sync"), cfg)

        environments.remove_environment("basecamp", cfg)

        assert environments.get_environment("basecamp", cfg) is None

    def test_remove_missing_is_noop(self, cfg: Settings) -> None:
        environments.remove_environment("nope", cfg)

        assert environments.load_environments(cfg) == {}

    def test_set_preserves_other_top_level_keys(self, cfg: Settings) -> None:
        cfg._write({"install_dir": "/tmp/ws", "projects": {"demo": {"repo_root": "demo"}}})

        environments.set_environment("basecamp", EnvironmentConfig(setup="uv sync"), cfg)

        data = json.loads(cfg.path.read_text())
        assert data["install_dir"] == "/tmp/ws"
        assert data["projects"] == {"demo": {"repo_root": "demo"}}
        assert data["environments"]["basecamp"] == {"setup": "uv sync"}
