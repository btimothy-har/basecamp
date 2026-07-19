"""Tests for basecamp project configuration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import basecamp.core.projects as project_config
from basecamp.core.exceptions import LauncherError
from basecamp.core.settings import CONFIG_VERSION, Settings


@pytest.fixture
def cfg(tmp_path: Path) -> Settings:
    """Return a Settings instance backed by a temp config file."""
    return Settings(tmp_path / "config.json")


class TestProjectConfigSchema:
    """Project config schema serialization in the unified config.json."""

    def test_save_and_load_projects_uses_repo_root_schema(self, cfg: Settings) -> None:
        project_config.save_projects(
            {
                "demo": project_config.ProjectConfig(
                    repo_root="src/demo",
                    additional_dirs=["src/shared"],
                    description="Demo",
                ),
            },
            cfg,
        )

        data = json.loads(cfg.path.read_text())
        assert data["version"] == CONFIG_VERSION
        assert data["projects"]["demo"]["repo_root"] == "src/demo"
        assert data["projects"]["demo"]["additional_dirs"] == ["src/shared"]

        loaded = project_config.load_projects(cfg)
        assert loaded["demo"].repo_root == "src/demo"
        assert loaded["demo"].additional_dirs == ["src/shared"]

    def test_project_config_rejects_legacy_dirs(self) -> None:
        with pytest.raises(ValidationError):
            project_config.ProjectConfig(
                repo_root="src/demo",
                dirs=["src/demo"],
            )

    def test_project_config_rejects_obsolete_bigquery(self) -> None:
        with pytest.raises(ValidationError):
            project_config.ProjectConfig(
                repo_root="src/demo",
                bigquery={"enabled": True},
            )

    def test_load_projects_empty_when_missing(self, cfg: Settings) -> None:
        assert project_config.load_projects(cfg) == {}

    def test_save_projects_preserves_other_sections(self, cfg: Settings) -> None:
        # Projects share config.json with environments/model_aliases; a write must
        # never clobber a sibling section (the whole point of the consolidation).
        cfg._write(
            {
                "environments": {"acme/widget": {"setup": "uv sync"}},
                "model_aliases": {"fast": "claude-haiku-4-5"},
                "stale_setting": {"preserve": True},
            }
        )

        project_config.save_projects(
            {"myproj": project_config.ProjectConfig(repo_root="myproj")},
            cfg,
        )

        data = json.loads(cfg.path.read_text())
        assert data["version"] == CONFIG_VERSION
        assert data["projects"]["myproj"]["repo_root"] == "myproj"
        assert data["environments"] == {"acme/widget": {"setup": "uv sync"}}
        assert data["model_aliases"] == {"fast": "claude-haiku-4-5"}
        assert data["stale_setting"] == {"preserve": True}

    def test_load_projects_wraps_bad_record_in_launcher_error(self, cfg: Settings) -> None:
        # A malformed record yields a clean LauncherError (caught by the CLI),
        # never a raw pydantic ValidationError traceback.
        cfg._write({"projects": {"demo": {"repo_root": 123}}})

        with pytest.raises(LauncherError):
            project_config.load_projects(cfg)

    def test_load_projects_strips_retired_working_style(self, cfg: Settings) -> None:
        # A config.json written by an older basecamp seeded `working_style`; the
        # field is gone from the model (extra="forbid" would reject it), so load
        # must strip it rather than raise. It is dropped, not migrated.
        cfg._write({"projects": {"demo": {"repo_root": "src/demo", "working_style": "engineering"}}})

        loaded = project_config.load_projects(cfg)

        assert loaded["demo"].repo_root == "src/demo"
        assert "working_style" not in loaded["demo"].model_dump()
