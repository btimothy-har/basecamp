"""Tests for basecamp-workspace project configuration."""

from __future__ import annotations

import json
from pathlib import Path

import basecamp.workspace.projects as project_config
import pytest
from basecamp.core.settings import Settings
from basecamp.workspace.migrations import migrate_project_dirs
from pydantic import ValidationError


@pytest.fixture
def cfg(tmp_path: Path) -> Settings:
    """Return a Settings instance backed by a temp config file."""
    return Settings(tmp_path / "config.json")


class TestProjectDirsMigration:
    """Legacy dirs-to-repo-root migration."""

    def test_migrate_legacy_project_dirs(self, cfg: Settings) -> None:
        cfg._write(
            {
                "install_dir": "/tmp/ws",
                "projects": {
                    "demo": {
                        "dirs": ["src/demo", "src/shared"],
                        "description": "Demo",
                    },
                },
            }
        )

        assert migrate_project_dirs(cfg) is True
        assert migrate_project_dirs(cfg) is False

        data = json.loads(cfg.path.read_text())
        assert data["install_dir"] == "/tmp/ws"
        assert data["projects"]["demo"] == {
            "repo_root": "src/demo",
            "additional_dirs": ["src/shared"],
            "description": "Demo",
        }

    def test_load_projects_migrates_legacy_project_dirs(self, cfg: Settings) -> None:
        cfg._write({"projects": {"demo": {"dirs": ["src/demo", "src/shared"]}}})

        projects = project_config.load_projects(cfg)

        assert projects["demo"].repo_root == "src/demo"
        assert projects["demo"].additional_dirs == ["src/shared"]
        data = json.loads(cfg.path.read_text())
        assert "dirs" not in data["projects"]["demo"]

    def test_migrate_noops_for_new_project_schema(self, cfg: Settings) -> None:
        cfg._write(
            {
                "projects": {
                    "demo": {
                        "repo_root": "src/demo",
                        "additional_dirs": ["src/shared"],
                    },
                },
            }
        )
        before = cfg.path.read_text()

        assert migrate_project_dirs(cfg) is False
        assert cfg.path.read_text() == before

    def test_migrate_leaves_empty_legacy_dirs_untouched(self, cfg: Settings) -> None:
        cfg._write({"projects": {"demo": {"dirs": []}}})
        before = cfg.path.read_text()

        assert migrate_project_dirs(cfg) is False
        assert cfg.path.read_text() == before

    def test_save_projects_migrates_legacy_project_dirs(self, cfg: Settings) -> None:
        cfg.set_section("projects", {"demo": {"dirs": ["src/demo", "src/shared"]}})

        projects = project_config.load_projects(cfg)

        assert projects["demo"].repo_root == "src/demo"
        assert projects["demo"].additional_dirs == ["src/shared"]

    def test_migrate_preserves_explicit_new_fields(self, cfg: Settings) -> None:
        cfg._write(
            {
                "projects": {
                    "demo": {
                        "repo_root": "src/demo",
                        "additional_dirs": ["src/explicit"],
                        "dirs": ["src/legacy", "src/legacy-extra"],
                    },
                },
            }
        )

        assert migrate_project_dirs(cfg) is True

        data = json.loads(cfg.path.read_text())
        assert data["projects"]["demo"] == {
            "repo_root": "src/demo",
            "additional_dirs": ["src/explicit"],
        }


class TestProjectConfigSchema:
    """Project config schema serialization."""

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
        assert data["version"] == project_config.PROJECTS_CONFIG_VERSION
        assert "dirs" not in data["projects"]["demo"]
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

    def test_save_projects_preserves_unknown_top_level_keys(self, cfg: Settings) -> None:
        cfg._write({"stale_setting": {"preserve": True}})

        project_config.save_projects(
            {"myproj": project_config.ProjectConfig(repo_root="myproj")},
            cfg,
        )

        data = json.loads(cfg.path.read_text())
        assert data["version"] == project_config.PROJECTS_CONFIG_VERSION
        assert data["projects"]["myproj"]["repo_root"] == "myproj"
        assert data["projects"]["myproj"]["additional_dirs"] == []
        assert data["stale_setting"] == {"preserve": True}
