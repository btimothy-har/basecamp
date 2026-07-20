"""Tests for basecamp.core.settings — generic locked JSON Settings."""

from __future__ import annotations

import json
from pathlib import Path

from basecamp.core.paths import DEFAULT_CONFIG_PATH
from basecamp.core.settings import CONFIG_VERSION, Settings


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


class TestInstallMetadata:
    def test_set_install_metadata_preserves_other_sections_and_drops_stale_modules(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        cfg._write(
            {
                "install_dir": "/tmp/old",
                "installed_modules": ["core"],
                "logseq": {"graph_dir": "~/logseq"},
                "environments": {"acme/app": {"setup": "uv sync"}},
            }
        )

        cfg.set_install_metadata(install_dir="/tmp/ws")

        data = json.loads(cfg.path.read_text())
        assert data == {
            "version": CONFIG_VERSION,
            "install_dir": "/tmp/ws",
            "logseq": {"graph_dir": "~/logseq"},
            "environments": {"acme/app": {"setup": "uv sync"}},
        }


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

    def test_update_if_changed_skips_and_applies_writes(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)

        assert cfg.update_if_changed(lambda _data: False) is False
        assert not cfg.path.exists()

        def add_value(data: dict) -> bool:
            data["value"] = 1
            return True

        assert cfg.update_if_changed(add_value) is True
        assert json.loads(cfg.path.read_text()) == {"value": 1}


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
