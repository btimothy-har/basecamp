"""Tests for observer config persistence."""

import json

import pytest
from observer.services import config


class TestWrite:
    def test_creates_file_with_correct_content(self):
        config._write({"extraction_model": "sonnet"})

        assert config.CONFIG_FILE.exists()
        data = json.loads(config.CONFIG_FILE.read_text())
        assert data == {"extraction_model": "sonnet"}

    def test_file_permissions_are_owner_only(self):
        config._write({"extraction_model": "sonnet"})

        mode = config.CONFIG_FILE.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got 0o{mode:03o}"

    def test_overwrites_existing_file(self):
        config._write({"extraction_model": "sonnet"})
        config._write({"extraction_model": "opus"})

        data = json.loads(config.CONFIG_FILE.read_text())
        assert data["extraction_model"] == "opus"

    def test_permissions_preserved_on_overwrite(self):
        config._write({"extraction_model": "sonnet"})
        config._write({"extraction_model": "opus"})

        mode = config.CONFIG_FILE.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got 0o{mode:03o}"


class TestGetSetPgUrl:
    """Legacy pg_url for migration support."""

    def test_returns_none_when_not_set(self):
        assert config.get_pg_url() is None

    def test_returns_stored_value(self):
        config._write({"pg_url": "postgresql://localhost/obs"})
        assert config.get_pg_url() == "postgresql://localhost/obs"


class TestGetSetMode:
    def test_default_returns_on(self):
        """No config file → default is 'on'."""
        assert config.get_mode() == "on"

    def test_on_returns_on(self):
        config.set_mode("on")
        assert config.get_mode() == "on"

    def test_off_returns_off(self):
        config.set_mode("off")
        assert config.get_mode() == "off"

    def test_full_returns_on(self):
        """Old 'full' mode maps to 'on'."""
        config._write({"mode": "full"})
        assert config.get_mode() == "on"

    def test_lite_returns_on(self):
        """Old 'lite' mode maps to 'on'."""
        config._write({"mode": "lite"})
        assert config.get_mode() == "on"

    def test_extraction_enabled_true_returns_on(self):
        """Old extraction_enabled=True maps to 'on'."""
        config._write({"extraction_enabled": True})
        assert config.get_mode() == "on"

    def test_extraction_enabled_false_returns_off(self):
        """Old extraction_enabled=False maps to 'off'."""
        config._write({"extraction_enabled": False})
        assert config.get_mode() == "off"

    def test_mode_takes_precedence_over_extraction_enabled(self):
        """When both exist, 'mode' wins."""
        config._write({"mode": "off", "extraction_enabled": True})
        assert config.get_mode() == "off"

    def test_set_mode_rejects_invalid(self):
        with pytest.raises(ValueError, match="Invalid mode"):
            config.set_mode("full")

    def test_set_mode_cleans_extraction_enabled(self):
        """set_mode removes the old extraction_enabled key."""
        config._write({"extraction_enabled": True})
        config.set_mode("on")
        data = json.loads(config.CONFIG_FILE.read_text())
        assert "extraction_enabled" not in data
        assert data["mode"] == "on"
