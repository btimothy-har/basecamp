"""Tests for core.settings — Settings class with file locking."""

from __future__ import annotations

import json
from pathlib import Path

import basecamp.config.project as project_config
import pytest
from basecamp.settings import Settings


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
    """Public property API: install_dir, projects, and global defaults."""

    def test_install_dir_empty(self, cfg: Settings) -> None:
        assert cfg.install_dir is None

    def test_install_dir_set_and_get(self, cfg: Settings) -> None:
        cfg.install_dir = "/tmp/ws"
        assert cfg.install_dir == "/tmp/ws"

    def test_projects_empty(self, cfg: Settings) -> None:
        assert cfg.projects == {}

    def test_projects_set_and_get(self, cfg: Settings) -> None:
        projects = {"myproj": {"dirs": ["~/myproj"]}}
        cfg.projects = projects
        assert cfg.projects == projects

    def test_install_dir_preserves_projects(self, cfg: Settings) -> None:
        projects = {"myproj": {"dirs": ["~/myproj"]}}
        cfg.projects = projects
        cfg.install_dir = "/tmp/ws"

        data = json.loads(cfg.path.read_text())
        assert data["install_dir"] == "/tmp/ws"
        assert data["projects"] == projects

    def test_projects_preserves_install_dir(self, cfg: Settings) -> None:
        cfg.install_dir = "/tmp/ws"
        cfg.projects = {"myproj": {"dirs": ["~/myproj"]}}

        data = json.loads(cfg.path.read_text())
        assert data["install_dir"] == "/tmp/ws"
        assert data["projects"]["myproj"] == {"dirs": ["~/myproj"]}

    def test_logseq_graph_empty(self, cfg: Settings) -> None:
        assert cfg.logseq_graph is None

    def test_logseq_graph_set_and_get(self, cfg: Settings) -> None:
        cfg.logseq_graph = "Documents/brain"
        assert cfg.logseq_graph == "Documents/brain"

    def test_logseq_graph_preserves_other_settings(self, cfg: Settings) -> None:
        cfg.install_dir = "/tmp/ws"
        cfg.projects = {"proj": {"dirs": ["~/proj"]}}
        cfg.logseq_graph = "Documents/brain"

        data = json.loads(cfg.path.read_text())
        assert data["install_dir"] == "/tmp/ws"
        assert data["projects"] == {"proj": {"dirs": ["~/proj"]}}
        assert data["logseq_graph"] == "Documents/brain"

    def test_timezone_empty(self, cfg: Settings) -> None:
        assert cfg.timezone is None

    def test_timezone_set_and_get(self, cfg: Settings) -> None:
        cfg.timezone = "America/Toronto"
        assert cfg.timezone == "America/Toronto"

    def test_timezone_preserves_other_settings(self, cfg: Settings) -> None:
        cfg.install_dir = "/tmp/ws"
        cfg.logseq_graph = "Documents/brain"
        cfg.timezone = "America/Toronto"

        data = json.loads(cfg.path.read_text())
        assert data["install_dir"] == "/tmp/ws"
        assert data["logseq_graph"] == "Documents/brain"
        assert data["timezone"] == "America/Toronto"

    def test_bigquery_empty(self, cfg: Settings) -> None:
        assert cfg.bigquery == {}

    def test_bigquery_set_and_get(self, cfg: Settings) -> None:
        bigquery = {
            "enabled": True,
            "default_project_id": "analytics-prod",
            "default_location": "US",
            "default_output_format": "json",
            "default_max_rows": 1000,
            "auto_dry_run": True,
        }

        cfg.bigquery = bigquery

        assert cfg.bigquery == bigquery

    def test_bigquery_preserves_other_settings(self, cfg: Settings) -> None:
        cfg.install_dir = "/tmp/ws"
        cfg.bigquery = {"enabled": False}

        data = json.loads(cfg.path.read_text())
        assert data["install_dir"] == "/tmp/ws"
        assert data["bigquery"] == {"enabled": False}

    def test_bigquery_clear(self, cfg: Settings) -> None:
        cfg.bigquery = {"enabled": True}
        cfg.bigquery = None

        assert "bigquery" not in json.loads(cfg.path.read_text())


class TestProjectBigQueryConfig:
    """Project-level BigQuery config serialization."""

    def test_save_and_load_projects_preserves_bigquery(
        self,
        cfg: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(project_config, "settings", cfg)
        bigquery = project_config.BigQueryConfig(
            enabled=True,
            default_project_id="analytics-prod",
            default_location="US",
            default_output_format="csv",
            default_max_rows=500,
            auto_dry_run=True,
        )

        project_config.save_projects(
            {
                "demo": project_config.ProjectConfig(
                    dirs=["src/demo"],
                    description="Demo",
                    bigquery=bigquery,
                ),
            },
        )

        data = json.loads(cfg.path.read_text())
        assert data["projects"]["demo"]["bigquery"] == {
            "enabled": True,
            "default_project_id": "analytics-prod",
            "default_location": "US",
            "default_output_format": "csv",
            "default_max_rows": 500,
            "auto_dry_run": True,
        }

        loaded = project_config.load_projects()
        assert loaded["demo"].bigquery == bigquery

    def test_save_projects_omits_absent_bigquery(
        self,
        cfg: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(project_config, "settings", cfg)

        project_config.save_projects({"demo": project_config.ProjectConfig(dirs=["src/demo"])})

        data = json.loads(cfg.path.read_text())
        assert "bigquery" not in data["projects"]["demo"]


class TestLocking:
    """Verify _locked_update creates the lock file and serialises access."""

    def test_lock_file_created(self, cfg: Settings) -> None:
        cfg.install_dir = "/tmp/test"
        assert cfg.path.with_suffix(".lock").exists()

    def test_sequential_updates_preserved(self, cfg: Settings) -> None:
        cfg.install_dir = "/tmp/ws"
        cfg.projects = {"proj": {"dirs": ["~/proj"]}}

        data = json.loads(cfg.path.read_text())
        assert data["install_dir"] == "/tmp/ws"
        assert data["projects"] == {"proj": {"dirs": ["~/proj"]}}

    def test_path_returns_configured_path(self, cfg: Settings) -> None:
        assert cfg.path.name == "config.json"
