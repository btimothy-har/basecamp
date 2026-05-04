"""Tests for observer-owned settings."""

import json

import pytest
from pi_observer import settings as settings_mod


class TestObserverConfigReadWrite:
    def test_extraction_model_default(self):
        assert settings_mod.settings.extraction_model == "anthropic:claude-sonnet-4-20250514"

    def test_summary_model_default(self):
        assert settings_mod.settings.summary_model == "anthropic:claude-3-5-haiku-latest"

    def test_set_extraction_model(self):
        settings_mod.settings.extraction_model = "openai:gpt-4o"
        assert settings_mod.settings.extraction_model == "openai:gpt-4o"

    def test_set_summary_model(self):
        settings_mod.settings.summary_model = "openai:gpt-4o-mini"
        assert settings_mod.settings.summary_model == "openai:gpt-4o-mini"

    def test_writes_top_level_observer_config(self):
        """Config writes land directly in pi-observer config.json."""
        settings_mod.settings.extraction_model = "anthropic:claude-haiku-4-5"

        data = json.loads(settings_mod.settings.path.read_text())
        assert data["extraction_model"] == "anthropic:claude-haiku-4-5"
        assert "observer" not in data


class TestObserverMode:
    def test_default_returns_on(self):
        """No config → default is 'on'."""
        assert settings_mod.settings.mode == "on"

    def test_on_returns_on(self):
        settings_mod.settings.mode = "on"
        assert settings_mod.settings.mode == "on"

    def test_off_returns_off(self):
        settings_mod.settings.mode = "off"
        assert settings_mod.settings.mode == "off"

    def test_set_mode_rejects_invalid(self):
        with pytest.raises(ValueError, match="Invalid mode"):
            settings_mod.settings.mode = "full"
