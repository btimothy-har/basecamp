"""Tests for core.settings — Settings class with file locking."""

from __future__ import annotations

import json
from pathlib import Path

import basecamp_cli.config.project as project_config
import pytest
from basecamp_cli.settings import Settings
from pydantic import ValidationError


@pytest.fixture
def cfg(tmp_path: Path) -> Settings:
    """Return a Settings instance backed by a temp config file."""
    return Settings(tmp_path / "config.json")


class TestReadWrite:
    """Basic read/write round-trips."""

    def test_read_missing_file(self, cfg: Settings) -> None:
        assert cfg._read() == {}

    def test_read_corrupt_json(self, cfg: Settings) -> None:
        cfg.path.parent.mkdir(parents=True, exist_ok=True)
        cfg.path.write_text("{invalid")
        assert cfg._read() == {}

    def test_read_non_dict_json(self, cfg: Settings) -> None:
        cfg.path.parent.mkdir(parents=True, exist_ok=True)
        cfg.path.write_text("[1, 2, 3]")
        assert cfg._read() == {}

    def test_write_then_read(self, cfg: Settings) -> None:
        cfg._write({"install_dir": "/tmp/test"})
        assert cfg._read() == {"install_dir": "/tmp/test"}


class TestProperties:
    """Public property API: install_dir and projects."""

    def test_install_dir_empty(self, cfg: Settings) -> None:
        assert cfg.install_dir is None

    def test_install_dir_set_and_get(self, cfg: Settings) -> None:
        cfg.install_dir = "/tmp/ws"
        assert cfg.install_dir == "/tmp/ws"

    def test_projects_empty(self, cfg: Settings) -> None:
        assert cfg.projects == {}

    def test_projects_set_and_get(self, cfg: Settings) -> None:
        projects = {"myproj": {"repo_root": "myproj", "additional_dirs": []}}
        cfg.projects = projects
        assert cfg.projects == projects

    def test_install_dir_preserves_projects(self, cfg: Settings) -> None:
        projects = {"myproj": {"repo_root": "myproj", "additional_dirs": []}}
        cfg.projects = projects
        cfg.install_dir = "/tmp/ws"

        data = json.loads(cfg.path.read_text())
        assert data["install_dir"] == "/tmp/ws"
        assert data["projects"] == projects

    def test_projects_preserves_install_dir(self, cfg: Settings) -> None:
        cfg.install_dir = "/tmp/ws"
        cfg.projects = {"myproj": {"repo_root": "myproj", "additional_dirs": []}}

        data = json.loads(cfg.path.read_text())
        assert data["install_dir"] == "/tmp/ws"
        assert data["projects"]["myproj"] == {"repo_root": "myproj", "additional_dirs": []}

    def test_writes_preserve_unknown_top_level_keys(self, cfg: Settings) -> None:
        cfg._write({"stale_setting": {"preserve": True}})

        cfg.install_dir = "/tmp/ws"
        cfg.projects = {"myproj": {"repo_root": "myproj", "additional_dirs": []}}

        data = json.loads(cfg.path.read_text())
        assert data["install_dir"] == "/tmp/ws"
        assert data["projects"] == {"myproj": {"repo_root": "myproj", "additional_dirs": []}}
        assert data["stale_setting"] == {"preserve": True}


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

        assert cfg.migrate_project_dirs() is True
        assert cfg.migrate_project_dirs() is False

        data = json.loads(cfg.path.read_text())
        assert data["install_dir"] == "/tmp/ws"
        assert data["projects"]["demo"] == {
            "repo_root": "src/demo",
            "additional_dirs": ["src/shared"],
            "description": "Demo",
        }

    def test_projects_getter_migrates_legacy_project_dirs(self, cfg: Settings) -> None:
        cfg._write({"projects": {"demo": {"dirs": ["src/demo", "src/shared"]}}})

        assert cfg.projects == {
            "demo": {
                "repo_root": "src/demo",
                "additional_dirs": ["src/shared"],
            }
        }

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

        assert cfg.migrate_project_dirs() is False
        assert cfg.path.read_text() == before

    def test_migrate_leaves_empty_legacy_dirs_untouched(self, cfg: Settings) -> None:
        cfg._write({"projects": {"demo": {"dirs": []}}})
        before = cfg.path.read_text()

        assert cfg.migrate_project_dirs() is False
        assert cfg.path.read_text() == before

    def test_projects_setter_migrates_legacy_project_dirs(self, cfg: Settings) -> None:
        cfg.projects = {"demo": {"dirs": ["src/demo", "src/shared"]}}

        assert cfg.projects == {
            "demo": {
                "repo_root": "src/demo",
                "additional_dirs": ["src/shared"],
            }
        }

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

        assert cfg.migrate_project_dirs() is True

        data = json.loads(cfg.path.read_text())
        assert data["projects"]["demo"] == {
            "repo_root": "src/demo",
            "additional_dirs": ["src/explicit"],
        }


class TestProjectConfigSchema:
    """Project config schema serialization."""

    def test_save_and_load_projects_uses_repo_root_schema(
        self,
        cfg: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(project_config, "settings", cfg)

        project_config.save_projects(
            {
                "demo": project_config.ProjectConfig(
                    repo_root="src/demo",
                    additional_dirs=["src/shared"],
                    description="Demo",
                ),
            },
        )

        data = json.loads(cfg.path.read_text())
        assert "dirs" not in data["projects"]["demo"]
        assert data["projects"]["demo"]["repo_root"] == "src/demo"
        assert data["projects"]["demo"]["additional_dirs"] == ["src/shared"]

        loaded = project_config.load_projects()
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


class TestLocking:
    """Verify _locked_update creates the lock file and serialises access."""

    def test_lock_file_created(self, cfg: Settings) -> None:
        cfg.install_dir = "/tmp/test"
        assert cfg.path.with_suffix(".lock").exists()

    def test_sequential_updates_preserved(self, cfg: Settings) -> None:
        cfg.install_dir = "/tmp/ws"
        cfg.projects = {"proj": {"repo_root": "proj", "additional_dirs": []}}

        data = json.loads(cfg.path.read_text())
        assert data["install_dir"] == "/tmp/ws"
        assert data["projects"] == {"proj": {"repo_root": "proj", "additional_dirs": []}}

    def test_path_returns_configured_path(self, cfg: Settings) -> None:
        assert cfg.path.name == "config.json"
