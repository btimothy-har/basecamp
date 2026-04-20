"""Tests for observer config via settings.observer namespace."""

import json

import pytest
from basecamp import settings as settings_mod


class TestObserverConfigReadWrite:
    def test_extraction_model_default(self):
        assert settings_mod.settings.observer.extraction_model == "anthropic:claude-sonnet-4-20250514"

    def test_summary_model_default(self):
        assert settings_mod.settings.observer.summary_model == "anthropic:claude-3-5-haiku-latest"

    def test_set_extraction_model(self):
        settings_mod.settings.observer.extraction_model = "openai:gpt-4o"
        assert settings_mod.settings.observer.extraction_model == "openai:gpt-4o"

    def test_set_summary_model(self):
        settings_mod.settings.observer.summary_model = "openai:gpt-4o-mini"
        assert settings_mod.settings.observer.summary_model == "openai:gpt-4o-mini"

    def test_writes_under_observer_key(self):
        """Config writes land under the 'observer' key in config.json."""
        settings_mod.settings.observer.extraction_model = "anthropic:claude-haiku-4-5"

        data = json.loads(settings_mod.settings.path.read_text())
        assert "observer" in data
        assert data["observer"]["extraction_model"] == "anthropic:claude-haiku-4-5"


class TestObserverMode:
    def test_default_returns_on(self):
        """No config → default is 'on'."""
        assert settings_mod.settings.observer.mode == "on"

    def test_on_returns_on(self):
        settings_mod.settings.observer.mode = "on"
        assert settings_mod.settings.observer.mode == "on"

    def test_off_returns_off(self):
        settings_mod.settings.observer.mode = "off"
        assert settings_mod.settings.observer.mode == "off"

    def test_set_mode_rejects_invalid(self):
        with pytest.raises(ValueError, match="Invalid mode"):
            settings_mod.settings.observer.mode = "full"
