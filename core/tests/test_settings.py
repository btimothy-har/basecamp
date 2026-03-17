"""Tests for core.settings — Settings class with file locking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.settings import Settings


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
    """Public property API: install_dir, projects."""

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
