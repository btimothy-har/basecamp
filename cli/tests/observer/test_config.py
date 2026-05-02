"""Tests for observer config via settings.observer namespace."""

import json

import pytest
from basecamp import settings as settings_mod
from basecamp.settings import ProviderConfig


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

    def test_writes_under_observer_models_key(self):
        """Config writes land under 'observer.models' in new nested shape."""
        settings_mod.settings.observer.extraction_model = "anthropic:claude-haiku-4-5"

        data = json.loads(settings_mod.settings.path.read_text())
        assert "observer" in data
        assert data["observer"]["models"]["extraction"] == "anthropic:claude-haiku-4-5"


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


class TestObserverLegacyFallback:
    """Tests for legacy config shape fallback."""

    def test_legacy_extraction_model_read(self):
        """Legacy observer.extraction_model is read when new shape absent."""
        settings_mod.settings._write({"observer": {"extraction_model": "openai:gpt-4-turbo"}})
        assert settings_mod.settings.observer.extraction_model == "openai:gpt-4-turbo"

    def test_legacy_summary_model_read(self):
        """Legacy observer.summary_model is read when new shape absent."""
        settings_mod.settings._write({"observer": {"summary_model": "openai:gpt-4o-mini"}})
        assert settings_mod.settings.observer.summary_model == "openai:gpt-4o-mini"

    def test_new_shape_takes_precedence_over_legacy(self):
        """New observer.models.* takes precedence over legacy fields."""
        settings_mod.settings._write(
            {
                "observer": {
                    "extraction_model": "legacy:model",
                    "summary_model": "legacy:summary",
                    "models": {
                        "extraction": "new:extraction",
                        "summary": "new:summary",
                    },
                }
            }
        )
        assert settings_mod.settings.observer.extraction_model == "new:extraction"
        assert settings_mod.settings.observer.summary_model == "new:summary"

    def test_model_refs_uses_legacy_when_no_models_key(self):
        """model_refs falls back to legacy fields if no models key."""
        settings_mod.settings._write(
            {
                "observer": {
                    "extraction_model": "legacy:extraction",
                    "summary_model": "legacy:summary",
                }
            }
        )
        refs = settings_mod.settings.observer.model_refs
        assert refs["extraction"] == "legacy:extraction"
        assert refs["summary"] == "legacy:summary"


class TestObserverModelRefs:
    """Tests for model_refs property."""

    def test_model_refs_defaults(self):
        """model_refs returns defaults when nothing configured."""
        refs = settings_mod.settings.observer.model_refs
        assert refs["summary"] == "anthropic:claude-3-5-haiku-latest"
        assert refs["extraction"] == "anthropic:claude-sonnet-4-20250514"

    def test_model_refs_from_new_shape(self):
        """model_refs reads from new observer.models shape."""
        settings_mod.settings._write(
            {
                "observer": {
                    "models": {
                        "summary": "openai:gpt-4o-mini",
                        "extraction": "openai:gpt-4o",
                    }
                }
            }
        )
        refs = settings_mod.settings.observer.model_refs
        assert refs["summary"] == "openai:gpt-4o-mini"
        assert refs["extraction"] == "openai:gpt-4o"

    def test_model_refs_setter(self):
        """model_refs setter writes new shape."""
        settings_mod.settings.observer.model_refs = {
            "summary": "test:summary",
            "extraction": "test:extraction",
        }
        data = json.loads(settings_mod.settings.path.read_text())
        assert data["observer"]["models"] == {
            "summary": "test:summary",
            "extraction": "test:extraction",
        }


class TestObserverProviderConfigs:
    """Tests for provider_configs property."""

    def test_provider_configs_defaults(self):
        """provider_configs returns defaults for openai and anthropic."""
        providers = settings_mod.settings.observer.provider_configs

        assert "openai" in providers
        assert providers["openai"].api_key_env == "OPENAI_API_KEY"
        assert providers["openai"].base_url_env == "OPENAI_BASE_URL"

        assert "anthropic" in providers
        assert providers["anthropic"].api_key_env == "ANTHROPIC_API_KEY"
        assert providers["anthropic"].base_url_env == "ANTHROPIC_BASE_URL"

    def test_provider_configs_custom_override(self):
        """Custom provider config overrides defaults."""
        settings_mod.settings._write(
            {
                "observer": {
                    "providers": {
                        "openai": {
                            "api_key_env": "MY_OPENAI_KEY",
                            "base_url_env": "MY_OPENAI_URL",
                        }
                    }
                }
            }
        )
        providers = settings_mod.settings.observer.provider_configs
        assert providers["openai"].api_key_env == "MY_OPENAI_KEY"
        assert providers["openai"].base_url_env == "MY_OPENAI_URL"
        assert providers["anthropic"].api_key_env == "ANTHROPIC_API_KEY"

    def test_provider_configs_partial_override_keeps_provider_defaults(self):
        """Partial provider config overrides only the configured fields."""
        settings_mod.settings._write(
            {
                "observer": {
                    "providers": {
                        "openai": {
                            "base_url_env": "MY_OPENAI_URL",
                        }
                    }
                }
            }
        )
        providers = settings_mod.settings.observer.provider_configs
        assert providers["openai"].api_key_env == "OPENAI_API_KEY"
        assert providers["openai"].base_url_env == "MY_OPENAI_URL"

    def test_provider_configs_additional_provider(self):
        """Can add new providers beyond defaults."""
        settings_mod.settings._write(
            {
                "observer": {
                    "providers": {
                        "ollama": {
                            "api_key_env": "OLLAMA_API_KEY",
                            "base_url_env": "OLLAMA_BASE_URL",
                        }
                    }
                }
            }
        )
        providers = settings_mod.settings.observer.provider_configs
        assert "ollama" in providers
        assert providers["ollama"].api_key_env == "OLLAMA_API_KEY"

    def test_provider_configs_setter(self):
        """provider_configs setter writes to config."""
        settings_mod.settings.observer.provider_configs = {
            "custom": ProviderConfig(api_key_env="CUSTOM_KEY", base_url_env="CUSTOM_URL"),
        }
        data = json.loads(settings_mod.settings.path.read_text())
        assert data["observer"]["providers"] == {
            "custom": {"api_key_env": "CUSTOM_KEY", "base_url_env": "CUSTOM_URL"},
        }

    def test_set_provider_single(self):
        """set_provider sets a single provider config."""
        settings_mod.settings.observer.set_provider(
            "azure", ProviderConfig(api_key_env="AZURE_KEY", base_url_env="AZURE_URL")
        )
        data = json.loads(settings_mod.settings.path.read_text())
        assert data["observer"]["providers"]["azure"] == {
            "api_key_env": "AZURE_KEY",
            "base_url_env": "AZURE_URL",
        }


class TestProviderConfig:
    """Tests for ProviderConfig class."""

    def test_to_dict(self):
        cfg = ProviderConfig(api_key_env="KEY", base_url_env="URL")
        assert cfg.to_dict() == {"api_key_env": "KEY", "base_url_env": "URL"}

    def test_from_dict(self):
        cfg = ProviderConfig.from_dict({"api_key_env": "KEY", "base_url_env": "URL"})
        assert cfg.api_key_env == "KEY"
        assert cfg.base_url_env == "URL"

    def test_from_dict_missing_base_url(self):
        cfg = ProviderConfig.from_dict({"api_key_env": "KEY"})
        assert cfg.api_key_env == "KEY"
        assert cfg.base_url_env is None

    def test_equality(self):
        cfg1 = ProviderConfig(api_key_env="KEY", base_url_env="URL")
        cfg2 = ProviderConfig(api_key_env="KEY", base_url_env="URL")
        assert cfg1 == cfg2

    def test_inequality(self):
        cfg1 = ProviderConfig(api_key_env="KEY1", base_url_env="URL")
        cfg2 = ProviderConfig(api_key_env="KEY2", base_url_env="URL")
        assert cfg1 != cfg2

    def test_repr(self):
        cfg = ProviderConfig(api_key_env="KEY", base_url_env="URL")
        assert repr(cfg) == "ProviderConfig(api_key_env='KEY', base_url_env='URL')"
