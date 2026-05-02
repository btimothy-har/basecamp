"""Tests for observer model resolver."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from basecamp.settings import ProviderConfig, Settings
from observer.exceptions import InvalidModelRefError, ProviderConfigError
from observer.llm import model_resolver
from observer.llm.model_resolver import (
    _SUPPORTED_PROVIDERS,
    ObserverOpenRouterProvider,
    _create_anthropic_provider,
    _create_model,
    _create_openai_provider,
    _create_openrouter_provider,
    parse_model_ref,
    resolve_model_ref,
    resolve_role_model,
)
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider


class TestParseModelRef:
    """Tests for parse_model_ref function."""

    def test_valid_openai_ref(self):
        """Valid openai: prefix is parsed."""
        provider, model_id = parse_model_ref("openai:gpt-4o")
        assert provider == "openai"
        assert model_id == "gpt-4o"

    def test_valid_anthropic_ref(self):
        """Valid anthropic: prefix is parsed."""
        provider, model_id = parse_model_ref("anthropic:claude-sonnet-4-20250514")
        assert provider == "anthropic"
        assert model_id == "claude-sonnet-4-20250514"

    def test_valid_openrouter_ref(self):
        """Valid openrouter: prefix is parsed."""
        provider, model_id = parse_model_ref("openrouter:anthropic/claude-3-opus")
        assert provider == "openrouter"
        assert model_id == "anthropic/claude-3-opus"

    def test_bare_model_raises_error(self):
        """Bare model without provider raises InvalidModelRefError."""
        with pytest.raises(InvalidModelRefError) as exc_info:
            parse_model_ref("gpt-4o-mini")
        assert "must use explicit 'provider:model_id' format" in str(exc_info.value)
        assert exc_info.value.model_ref == "gpt-4o-mini"

    def test_empty_ref_raises_error(self):
        """Empty model reference raises InvalidModelRefError."""
        with pytest.raises(InvalidModelRefError) as exc_info:
            parse_model_ref("")
        assert "cannot be empty" in str(exc_info.value)

    def test_whitespace_ref_raises_error(self):
        """Whitespace-only model reference raises InvalidModelRefError."""
        with pytest.raises(InvalidModelRefError) as exc_info:
            parse_model_ref("   ")
        assert "cannot be empty" in str(exc_info.value)

    def test_empty_provider_raises_error(self):
        """Empty provider raises InvalidModelRefError."""
        with pytest.raises(InvalidModelRefError) as exc_info:
            parse_model_ref(":gpt-4o")
        assert "provider cannot be empty" in str(exc_info.value)

    @pytest.mark.parametrize("model_ref", ["openai:", "openai:   "])
    def test_empty_model_id_raises_error(self, model_ref: str):
        """Empty model_id raises InvalidModelRefError."""
        with pytest.raises(InvalidModelRefError) as exc_info:
            parse_model_ref(model_ref)
        assert "model_id cannot be empty" in str(exc_info.value)

    def test_openai_chat_raises_error(self):
        """openai-chat: prefix raises InvalidModelRefError."""
        with pytest.raises(InvalidModelRefError) as exc_info:
            parse_model_ref("openai-chat:gpt-4o")
        assert "'openai-chat' provider is not supported" in str(exc_info.value)
        assert "Use 'openai:gpt-4o' instead" in str(exc_info.value)

    def test_openai_responses_raises_error(self):
        """openai-responses: prefix raises InvalidModelRefError."""
        with pytest.raises(InvalidModelRefError) as exc_info:
            parse_model_ref("openai-responses:gpt-4o")
        assert "'openai-responses' provider is not supported" in str(exc_info.value)
        assert "Use 'openai:gpt-4o' instead" in str(exc_info.value)

    def test_unknown_provider_raises_error(self):
        """Unknown provider raises InvalidModelRefError."""
        with pytest.raises(InvalidModelRefError) as exc_info:
            parse_model_ref("custom-provider:some-model")
        assert "unsupported provider 'custom-provider'" in str(exc_info.value)
        assert "anthropic" in str(exc_info.value)
        assert "openai" in str(exc_info.value)
        assert "openrouter" in str(exc_info.value)

    def test_supported_providers_set(self):
        """Verify the set of supported providers."""
        assert _SUPPORTED_PROVIDERS == {"openai", "anthropic", "openrouter"}


class TestResolveModelRef:
    """Tests for resolve_model_ref function."""

    def test_no_alias_with_valid_ref(self, monkeypatch, tmp_path):
        """Valid ref without alias is returned as-is."""
        test_settings = Settings(path=tmp_path / "config.json")
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        provider, model_id = resolve_model_ref("anthropic:claude-test")
        assert provider == "anthropic"
        assert model_id == "claude-test"

    def test_alias_resolution(self, monkeypatch, tmp_path):
        """Alias is resolved through settings.models."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.models = {"fast": "anthropic:claude-test"}
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        provider, model_id = resolve_model_ref("fast")
        assert provider == "anthropic"
        assert model_id == "claude-test"

    def test_alias_to_bare_model_raises_error(self, monkeypatch, tmp_path):
        """Alias pointing to bare model raises InvalidModelRefError."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.models = {"fast": "gpt-4o-mini"}
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        with pytest.raises(InvalidModelRefError) as exc_info:
            resolve_model_ref("fast")
        assert "must use explicit 'provider:model_id' format" in str(exc_info.value)

    def test_no_recursive_alias_resolution(self, monkeypatch, tmp_path):
        """Alias resolution is one level only."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.models = {
            "fast": "medium",
            "medium": "anthropic:claude-test",
        }
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        with pytest.raises(InvalidModelRefError) as exc_info:
            resolve_model_ref("fast")
        assert "must use explicit 'provider:model_id' format" in str(exc_info.value)


class TestCreateProviders:
    """Tests for provider creation functions."""

    def test_create_openai_provider_with_env_vars(self, monkeypatch):
        """OpenAI provider reads api_key and base_url from env."""
        monkeypatch.setenv("TEST_OPENAI_KEY", "test-key-123")
        monkeypatch.setenv("TEST_OPENAI_URL", "https://custom.openai.com")

        config = ProviderConfig(api_key_env="TEST_OPENAI_KEY", base_url_env="TEST_OPENAI_URL")

        with patch.object(OpenAIProvider, "__init__", return_value=None) as mock_init:
            _create_openai_provider(config)
            mock_init.assert_called_once_with(api_key="test-key-123", base_url="https://custom.openai.com")

    def test_create_anthropic_provider_with_env_vars(self, monkeypatch):
        """Anthropic provider reads api_key and base_url from env."""
        monkeypatch.setenv("TEST_ANTHROPIC_KEY", "test-anthropic-key")
        monkeypatch.setenv("TEST_ANTHROPIC_URL", "https://custom.anthropic.com")

        config = ProviderConfig(api_key_env="TEST_ANTHROPIC_KEY", base_url_env="TEST_ANTHROPIC_URL")

        with patch.object(AnthropicProvider, "__init__", return_value=None) as mock_init:
            _create_anthropic_provider(config)
            mock_init.assert_called_once_with(api_key="test-anthropic-key", base_url="https://custom.anthropic.com")

    def test_create_openrouter_provider_with_env_vars(self, monkeypatch):
        """OpenRouter provider reads api_key and base_url from env."""
        monkeypatch.setenv("TEST_OR_KEY", "test-or-key")
        monkeypatch.setenv("TEST_OR_URL", "https://custom.openrouter.ai")
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_APP_URL", raising=False)
        monkeypatch.delenv("OPENROUTER_APP_TITLE", raising=False)

        config = ProviderConfig(api_key_env="TEST_OR_KEY", base_url_env="TEST_OR_URL")

        provider = _create_openrouter_provider(config)
        assert isinstance(provider, ObserverOpenRouterProvider)
        assert provider.base_url == "https://custom.openrouter.ai"

    def test_openai_missing_api_key_without_base_url_raises(self, monkeypatch):
        """Missing OpenAI API key raises unless a custom endpoint is configured."""
        monkeypatch.delenv("MISSING_KEY", raising=False)
        monkeypatch.delenv("MISSING_URL", raising=False)

        config = ProviderConfig(api_key_env="MISSING_KEY", base_url_env="MISSING_URL")

        with pytest.raises(ProviderConfigError) as exc_info:
            _create_openai_provider(config)
        assert "MISSING_KEY" in str(exc_info.value)

    def test_openai_custom_endpoint_can_omit_api_key(self, monkeypatch):
        """OpenAI-compatible custom endpoints can run without a real API key."""
        monkeypatch.delenv("MISSING_KEY", raising=False)
        monkeypatch.setenv("CUSTOM_OPENAI_URL", "https://custom.openai.com")

        config = ProviderConfig(api_key_env="MISSING_KEY", base_url_env="CUSTOM_OPENAI_URL")

        with patch.object(OpenAIProvider, "__init__", return_value=None) as mock_init:
            _create_openai_provider(config)
            mock_init.assert_called_once_with(
                api_key="api-key-not-set",
                base_url="https://custom.openai.com",
            )

    def test_openai_uses_explicit_default_base_url(self, monkeypatch):
        """OpenAI does not fall back to OPENAI_BASE_URL when config clears it."""
        monkeypatch.setenv("TEST_OPENAI_KEY", "test-key-123")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://unconfigured.example.com")

        config = ProviderConfig(api_key_env="TEST_OPENAI_KEY")

        with patch.object(OpenAIProvider, "__init__", return_value=None) as mock_init:
            _create_openai_provider(config)
            mock_init.assert_called_once_with(
                api_key="test-key-123",
                base_url="https://api.openai.com/v1",
            )

    def test_anthropic_missing_api_key_raises(self, monkeypatch):
        """Anthropic does not fall back to ANTHROPIC_API_KEY for custom config."""
        monkeypatch.delenv("MISSING_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "default-key")

        config = ProviderConfig(api_key_env="MISSING_KEY")

        with pytest.raises(ProviderConfigError) as exc_info:
            _create_anthropic_provider(config)
        assert "MISSING_KEY" in str(exc_info.value)

    def test_openrouter_missing_api_key_raises(self, monkeypatch):
        """OpenRouter does not fall back to OPENROUTER_API_KEY for custom config."""
        monkeypatch.delenv("MISSING_KEY", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "default-key")

        config = ProviderConfig(api_key_env="MISSING_KEY")

        with pytest.raises(ProviderConfigError) as exc_info:
            _create_openrouter_provider(config)
        assert "MISSING_KEY" in str(exc_info.value)


class TestObserverOpenRouterProvider:
    """Tests for ObserverOpenRouterProvider subclass."""

    def test_default_base_url(self, monkeypatch):
        """Default base_url is OpenRouter's standard URL."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.delenv("OPENROUTER_APP_URL", raising=False)
        monkeypatch.delenv("OPENROUTER_APP_TITLE", raising=False)

        provider = ObserverOpenRouterProvider(api_key="test-key")
        assert provider.base_url == "https://openrouter.ai/api/v1"

    def test_custom_base_url(self, monkeypatch):
        """Custom base_url overrides default."""
        monkeypatch.delenv("OPENROUTER_APP_URL", raising=False)
        monkeypatch.delenv("OPENROUTER_APP_TITLE", raising=False)

        provider = ObserverOpenRouterProvider(
            api_key="test-key",
            base_url="https://my-proxy.example.com/v1",
        )
        assert provider.base_url == "https://my-proxy.example.com/v1"

    def test_name_property(self, monkeypatch):
        """Provider name is 'openrouter'."""
        monkeypatch.delenv("OPENROUTER_APP_URL", raising=False)
        monkeypatch.delenv("OPENROUTER_APP_TITLE", raising=False)

        provider = ObserverOpenRouterProvider(api_key="test-key")
        assert provider.name == "openrouter"


class TestCreateModel:
    """Tests for _create_model function."""

    def test_openai_creates_responses_model(self, monkeypatch, tmp_path):
        """openai provider creates OpenAIResponsesModel."""
        test_settings = Settings(path=tmp_path / "config.json")
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        model = _create_model("openai", "gpt-4o")
        assert isinstance(model, OpenAIResponsesModel)

    def test_anthropic_creates_anthropic_model(self, monkeypatch, tmp_path):
        """anthropic provider creates AnthropicModel."""
        test_settings = Settings(path=tmp_path / "config.json")
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        model = _create_model("anthropic", "claude-sonnet-4-20250514")
        assert isinstance(model, AnthropicModel)

    def test_openrouter_creates_openrouter_model(self, monkeypatch, tmp_path):
        """openrouter provider creates OpenRouterModel."""
        test_settings = Settings(path=tmp_path / "config.json")
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.delenv("OPENROUTER_APP_URL", raising=False)
        monkeypatch.delenv("OPENROUTER_APP_TITLE", raising=False)

        model = _create_model("openrouter", "anthropic/claude-3-opus")
        assert isinstance(model, OpenRouterModel)


class TestResolveRoleModel:
    """Tests for resolve_role_model function."""

    def test_resolves_summary_role(self, monkeypatch, tmp_path):
        """Summary role resolves through model_refs."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.observer.model_refs = {
            "summary": "anthropic:claude-test",
            "extraction": "anthropic:claude-other",
        }
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        model = resolve_role_model("summary")
        assert isinstance(model, AnthropicModel)

    def test_resolves_extraction_role(self, monkeypatch, tmp_path):
        """Extraction role resolves through model_refs."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.observer.model_refs = {
            "summary": "anthropic:claude-test",
            "extraction": "openai:gpt-4o",
        }
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        model = resolve_role_model("extraction")
        assert isinstance(model, OpenAIResponsesModel)

    def test_role_with_alias(self, monkeypatch, tmp_path):
        """Role model ref that is an alias gets resolved."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.models = {"fast": "anthropic:claude-fast"}
        test_settings.observer.model_refs = {
            "summary": "fast",
            "extraction": "anthropic:default",
        }
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        model = resolve_role_model("summary")
        assert isinstance(model, AnthropicModel)

    def test_role_with_bare_model_alias_raises(self, monkeypatch, tmp_path):
        """Role model ref alias to bare model raises error."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.models = {"fast": "gpt-4o-mini"}
        test_settings.observer.model_refs = {
            "summary": "fast",
            "extraction": "anthropic:default",
        }
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        with pytest.raises(InvalidModelRefError):
            resolve_role_model("summary")

    def test_uses_default_when_role_not_configured(self, monkeypatch, tmp_path):
        """Falls back to default when role not in model_refs."""
        test_settings = Settings(path=tmp_path / "config.json")
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        model = resolve_role_model("summary")
        assert isinstance(model, AnthropicModel)

    def test_arbitrary_model_id_accepted(self, monkeypatch, tmp_path):
        """Arbitrary/nonexistent model IDs are accepted without validation."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.observer.model_refs = {
            "summary": "anthropic:completely-fake-model-xyz",
            "extraction": "anthropic:default",
        }
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        model = resolve_role_model("summary")
        assert isinstance(model, AnthropicModel)


class TestProviderConfigIntegration:
    """Integration tests for provider config flow."""

    def test_default_provider_configs_used(self, monkeypatch, tmp_path):
        """Default provider configs are used when not overridden."""
        test_settings = Settings(path=tmp_path / "config.json")
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)
        monkeypatch.setenv("OPENAI_API_KEY", "default-openai-key")

        with patch.object(OpenAIProvider, "__init__", return_value=None) as mock_init:
            _create_model("openai", "gpt-4o")
            call_kwargs = mock_init.call_args.kwargs
            assert call_kwargs["api_key"] == "default-openai-key"

    def test_custom_provider_config_overrides_default(self, monkeypatch, tmp_path):
        """Custom provider config overrides default env var names."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.observer.set_provider(
            "openai",
            ProviderConfig(api_key_env="MY_CUSTOM_KEY"),
        )
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        monkeypatch.setenv("OPENAI_API_KEY", "default-key")
        monkeypatch.setenv("MY_CUSTOM_KEY", "custom-key")

        with patch.object(OpenAIProvider, "__init__", return_value=None) as mock_init:
            _create_model("openai", "gpt-4o")
            call_kwargs = mock_init.call_args.kwargs
            assert call_kwargs["api_key"] == "custom-key"

    def test_openrouter_default_config(self, monkeypatch, tmp_path):
        """OpenRouter uses default OPENROUTER_API_KEY env var."""
        test_settings = Settings(path=tmp_path / "config.json")
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)
        monkeypatch.setenv("OPENROUTER_API_KEY", "default-openrouter-key")
        monkeypatch.delenv("OPENROUTER_APP_URL", raising=False)
        monkeypatch.delenv("OPENROUTER_APP_TITLE", raising=False)

        model = _create_model("openrouter", "anthropic/claude-3-opus")
        assert isinstance(model, OpenRouterModel)
