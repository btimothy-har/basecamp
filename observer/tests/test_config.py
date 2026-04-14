"""Tests for observer config persistence."""

import json

import pytest
from observer.services.config import Config


class TestWrite:
    def test_creates_file_with_correct_content(self):
        cfg = Config.get()
        cfg._write({"extraction_model": "sonnet"})

        assert cfg._path.exists()
        data = json.loads(cfg._path.read_text())
        assert data == {"extraction_model": "sonnet"}

    def test_file_permissions_are_owner_only(self):
        cfg = Config.get()
        cfg._write({"extraction_model": "sonnet"})

        mode = cfg._path.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got 0o{mode:03o}"

    def test_overwrites_existing_file(self):
        cfg = Config.get()
        cfg._write({"extraction_model": "sonnet"})
        cfg._write({"extraction_model": "opus"})

        data = json.loads(cfg._path.read_text())
        assert data["extraction_model"] == "opus"

    def test_permissions_preserved_on_overwrite(self):
        cfg = Config.get()
        cfg._write({"extraction_model": "sonnet"})
        cfg._write({"extraction_model": "opus"})

        mode = cfg._path.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got 0o{mode:03o}"


class TestGetSetMode:
    def test_default_returns_on(self):
        """No config file → default is 'on'."""
        assert Config.get().mode == "on"

    def test_on_returns_on(self):
        cfg = Config.get()
        cfg.mode = "on"
        assert Config.get().mode == "on"

    def test_off_returns_off(self):
        cfg = Config.get()
        cfg.mode = "off"
        assert Config.get().mode == "off"

    def test_full_returns_on(self):
        """Old 'full' mode maps to 'on'."""
        cfg = Config.get()
        cfg._write({"mode": "full"})
        assert Config.get().mode == "on"

    def test_lite_returns_on(self):
        """Old 'lite' mode maps to 'on'."""
        cfg = Config.get()
        cfg._write({"mode": "lite"})
        assert Config.get().mode == "on"

    def test_extraction_enabled_true_returns_on(self):
        """Old extraction_enabled=True maps to 'on'."""
        cfg = Config.get()
        cfg._write({"extraction_enabled": True})
        assert Config.get().mode == "on"

    def test_extraction_enabled_false_returns_off(self):
        """Old extraction_enabled=False maps to 'off'."""
        cfg = Config.get()
        cfg._write({"extraction_enabled": False})
        assert Config.get().mode == "off"

    def test_mode_takes_precedence_over_extraction_enabled(self):
        """When both exist, 'mode' wins."""
        cfg = Config.get()
        cfg._write({"mode": "off", "extraction_enabled": True})
        assert Config.get().mode == "off"

    def test_set_mode_rejects_invalid(self):
        with pytest.raises(ValueError, match="Invalid mode"):
            Config.get().mode = "full"

    def test_set_mode_cleans_extraction_enabled(self):
        """set_mode removes the old extraction_enabled key."""
        cfg = Config.get()
        cfg._write({"extraction_enabled": True})
        cfg.mode = "on"
        data = json.loads(cfg._path.read_text())
        assert "extraction_enabled" not in data
        assert data["mode"] == "on"
