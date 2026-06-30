"""Tests for basecamp_core.settings — generic locked JSON Settings."""

from __future__ import annotations

import json
from pathlib import Path

from basecamp_core.paths import DEFAULT_CONFIG_PATH
from basecamp_core.settings import CONFIG_VERSION, Settings


def _cfg(tmp_path: Path) -> Settings:
    return Settings(tmp_path / "config.json")


class TestReadWrite:
    """Basic read/write round-trips and corrupt-file handling."""

    def test_read_missing_file(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        assert cfg._read() == {}

    def test_read_corrupt_json(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg.path.parent.mkdir(parents=True, exist_ok=True)
        cfg.path.write_text("{invalid")
        assert cfg._read() == {}

    def test_read_non_dict_json(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg.path.parent.mkdir(parents=True, exist_ok=True)
        cfg.path.write_text("[1, 2, 3]")
        assert cfg._read() == {}

    def test_write_then_read(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg._write({"install_dir": "/tmp/test"})
        assert cfg._read() == {"install_dir": "/tmp/test"}


class TestInstallDir:
    def test_install_dir_empty(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        assert cfg.install_dir is None

    def test_install_dir_set_and_get(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg.install_dir = "/tmp/ws"
        assert cfg.install_dir == "/tmp/ws"

    def test_install_dir_blank_string_is_none(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg._write({"install_dir": "   "})
        assert cfg.install_dir is None

    def test_install_dir_preserves_unknown_top_level_keys(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg._write({"stale_setting": {"preserve": True}})

        cfg.install_dir = "/tmp/ws"

        data = json.loads(cfg.path.read_text())
        assert data["version"] == CONFIG_VERSION
        assert data["install_dir"] == "/tmp/ws"
        assert data["stale_setting"] == {"preserve": True}


class TestInstalledModules:
    def test_installed_modules_empty(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        assert cfg.installed_modules == ()

    def test_installed_modules_normalizes_and_deduplicates(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg._write({"installed_modules": ["core", "", "tasks", "core", 42]})

        assert cfg.installed_modules == ("core", "tasks")

    def test_installed_modules_setter_persists_version_and_values(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)

        cfg.installed_modules = ["core", "workspace", "core"]

        data = json.loads(cfg.path.read_text())
        assert data["version"] == CONFIG_VERSION
        assert data["installed_modules"] == ["core", "workspace"]

    def test_set_install_metadata_writes_only_installer_metadata(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg._write({"projects": {"stale": {}}, "models": {"fast": "old"}})

        cfg.set_install_metadata(install_dir="/tmp/ws", installed_modules=["core", "swarm"])

        data = json.loads(cfg.path.read_text())
        assert data == {"version": CONFIG_VERSION, "install_dir": "/tmp/ws", "installed_modules": ["core", "swarm"]}


class TestSections:
    def test_get_section_missing_returns_empty_dict(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        assert cfg.get_section("things") == {}

    def test_get_section_non_dict_returns_empty_dict(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg._write({"things": [1, 2, 3]})
        assert cfg.get_section("things") == {}

    def test_get_section_returns_existing_dict(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg._write({"things": {"a": 1}})
        assert cfg.get_section("things") == {"a": 1}

    def test_set_section_creates_and_persists(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg.set_section("things", {"a": 1})

        assert cfg.get_section("things") == {"a": 1}
        data = json.loads(cfg.path.read_text())
        assert data["things"] == {"a": 1}

    def test_set_section_preserves_other_keys(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg.install_dir = "/tmp/ws"
        cfg.set_section("things", {"a": 1})

        data = json.loads(cfg.path.read_text())
        assert data["install_dir"] == "/tmp/ws"
        assert data["things"] == {"a": 1}


class TestUpdate:
    def test_update_applies_mutation_under_lock(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg._write({"count": 1})

        cfg.update(lambda data: data.update({"count": data["count"] + 1, "added": True}))

        data = json.loads(cfg.path.read_text())
        assert data == {"count": 2, "added": True}

    def test_update_preserves_unrelated_keys(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg._write({"keep": "me"})

        cfg.update(lambda data: data.setdefault("new", 42))

        data = json.loads(cfg.path.read_text())
        assert data == {"keep": "me", "new": 42}


class TestLocking:
    def test_lock_file_created_on_write(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg.install_dir = "/tmp/test"

        assert cfg.path.with_suffix(".lock").exists()

    def test_sequential_updates_preserved(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg.install_dir = "/tmp/ws"
        cfg.set_section("things", {"a": 1})

        data = json.loads(cfg.path.read_text())
        assert data["install_dir"] == "/tmp/ws"
        assert data["things"] == {"a": 1}

    def test_path_returns_configured_path(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        assert cfg.path.name == "config.json"

    def test_lock_path_is_sibling(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        assert cfg.lock_path == cfg.path.with_suffix(".lock")


class TestDefaults:
    def test_default_path_is_basecamp_config(self) -> None:
        # Settings constructed without a path defaults to the core constant.
        cfg = Settings()
        assert cfg.path == DEFAULT_CONFIG_PATH
