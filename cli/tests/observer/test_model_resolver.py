"""Tests for observer model resolver."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from basecamp.settings import ProviderConfig, Settings
from observer.llm import model_resolver
from observer.llm.model_resolver import (
    _CUSTOM_PROVIDERS,
    _create_provider,
    _provider_factory,
    normalize_model_ref,
    resolve_model_ref,
    resolve_role_model,
)
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider


class TestNormalizeModelRef:
    """Tests for normalize_model_ref function."""

    def test_bare_model_gets_openai_prefix(self):
        """Model without provider gets openai: prefix."""
        assert normalize_model_ref("gpt-4o-mini") == "openai:gpt-4o-mini"
        assert normalize_model_ref("gpt-4") == "openai:gpt-4"

    def test_anthropic_prefix_preserved(self):
        """anthropic: prefix is preserved."""
        assert normalize_model_ref("anthropic:claude-x") == "anthropic:claude-x"
        assert normalize_model_ref("anthropic:claude-sonnet-4-20250514") == "anthropic:claude-sonnet-4-20250514"

    def test_openai_prefix_preserved(self):
        """openai: prefix is preserved."""
        assert normalize_model_ref("openai:gpt-4o") == "openai:gpt-4o"

    def test_openai_responses_prefix_preserved(self):
        """openai-responses: prefix is preserved."""
        assert normalize_model_ref("openai-responses:gpt-x") == "openai-responses:gpt-x"

    def test_openrouter_prefix_preserved(self):
        """openrouter: prefix is preserved."""
        assert normalize_model_ref("openrouter:model-x") == "openrouter:model-x"

    def test_arbitrary_provider_prefix_preserved(self):
        """Any provider:model format is preserved."""
        assert normalize_model_ref("custom-provider:some-model") == "custom-provider:some-model"


class TestResolveModelRef:
    """Tests for resolve_model_ref function."""

    def test_no_alias_bare_model(self, monkeypatch, tmp_path):
        """Bare model without alias gets normalized."""
        test_settings = Settings(path=tmp_path / "config.json")
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        assert resolve_model_ref("gpt-4o-mini") == "openai:gpt-4o-mini"

    def test_alias_resolution(self, monkeypatch, tmp_path):
        """Alias is resolved through settings.models."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.models = {"fast": "anthropic:claude-test"}
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        assert resolve_model_ref("fast") == "anthropic:claude-test"

    def test_alias_to_bare_model_gets_normalized(self, monkeypatch, tmp_path):
        """Alias pointing to bare model gets openai prefix."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.models = {"fast": "gpt-4o-mini"}
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        assert resolve_model_ref("fast") == "openai:gpt-4o-mini"

    def test_no_recursive_alias_resolution(self, monkeypatch, tmp_path):
        """Alias resolution is one level only."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.models = {
            "fast": "medium",
            "medium": "anthropic:claude-test",
        }
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        assert resolve_model_ref("fast") == "openai:medium"

    def test_passthrough_when_not_aliased(self, monkeypatch, tmp_path):
        """Non-aliased model ref passes through unchanged (after normalization)."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.models = {"other": "something"}
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        assert resolve_model_ref("anthropic:claude-x") == "anthropic:claude-x"


class TestCreateProvider:
    """Tests for _create_provider helper."""

    def test_openai_provider_with_env_vars(self, monkeypatch):
        """OpenAI provider reads api_key and base_url from env."""
        monkeypatch.setenv("TEST_OPENAI_KEY", "test-key-123")
        monkeypatch.setenv("TEST_OPENAI_URL", "https://custom.openai.com")

        config = ProviderConfig(api_key_env="TEST_OPENAI_KEY", base_url_env="TEST_OPENAI_URL")

        with patch.object(OpenAIProvider, "__init__", return_value=None) as mock_init:
            _create_provider("openai", config)
            mock_init.assert_called_once_with(api_key="test-key-123", base_url="https://custom.openai.com")

    def test_openai_chat_uses_openai_provider(self, monkeypatch):
        """openai-chat provider variant uses OpenAIProvider."""
        monkeypatch.setenv("TEST_KEY", "key")
        config = ProviderConfig(api_key_env="TEST_KEY")

        with patch.object(OpenAIProvider, "__init__", return_value=None) as mock_init:
            _create_provider("openai-chat", config)
            mock_init.assert_called_once()

    def test_openai_responses_uses_openai_provider(self, monkeypatch):
        """openai-responses provider variant uses OpenAIProvider."""
        monkeypatch.setenv("TEST_KEY", "key")
        config = ProviderConfig(api_key_env="TEST_KEY")

        with patch.object(OpenAIProvider, "__init__", return_value=None) as mock_init:
            _create_provider("openai-responses", config)
            mock_init.assert_called_once()

    def test_anthropic_provider_with_env_vars(self, monkeypatch):
        """Anthropic provider reads api_key and base_url from env."""
        monkeypatch.setenv("TEST_ANTHROPIC_KEY", "test-anthropic-key")
        monkeypatch.setenv("TEST_ANTHROPIC_URL", "https://custom.anthropic.com")

        config = ProviderConfig(api_key_env="TEST_ANTHROPIC_KEY", base_url_env="TEST_ANTHROPIC_URL")

        with patch.object(AnthropicProvider, "__init__", return_value=None) as mock_init:
            _create_provider("anthropic", config)
            mock_init.assert_called_once_with(api_key="test-anthropic-key", base_url="https://custom.anthropic.com")

    def test_none_values_when_env_vars_missing(self, monkeypatch):
        """Provider receives None when env vars are not set."""
        monkeypatch.delenv("MISSING_KEY", raising=False)
        monkeypatch.delenv("MISSING_URL", raising=False)

        config = ProviderConfig(api_key_env="MISSING_KEY", base_url_env="MISSING_URL")

        with patch.object(OpenAIProvider, "__init__", return_value=None) as mock_init:
            _create_provider("openai", config)
            mock_init.assert_called_once_with(api_key=None, base_url=None)

    def test_none_config_passes_none_values(self):
        """None config results in None values passed to provider."""
        with patch.object(OpenAIProvider, "__init__", return_value=None) as mock_init:
            _create_provider("openai", None)
            mock_init.assert_called_once_with(api_key=None, base_url=None)

    def test_empty_env_var_treated_as_none(self, monkeypatch):
        """Empty environment variable treated as None."""
        monkeypatch.setenv("EMPTY_KEY", "")
        config = ProviderConfig(api_key_env="EMPTY_KEY")

        with patch.object(OpenAIProvider, "__init__", return_value=None) as mock_init:
            _create_provider("openai", config)
            mock_init.assert_called_once_with(api_key=None, base_url=None)


class TestProviderFactory:
    """Tests for _provider_factory function."""

    def test_custom_providers_list(self):
        """Verify the set of custom providers."""
        assert _CUSTOM_PROVIDERS == {"openai", "openai-chat", "openai-responses", "anthropic"}

    def test_openai_uses_custom_config(self, monkeypatch, tmp_path):
        """OpenAI provider uses settings.observer.provider_configs."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.observer.set_provider(
            "openai",
            ProviderConfig(api_key_env="CUSTOM_OPENAI_KEY"),
        )
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)
        monkeypatch.setenv("CUSTOM_OPENAI_KEY", "my-custom-key")

        with patch.object(OpenAIProvider, "__init__", return_value=None) as mock_init:
            _provider_factory("openai")
            mock_init.assert_called_once()
            call_kwargs = mock_init.call_args.kwargs
            assert call_kwargs["api_key"] == "my-custom-key"

    def test_openai_responses_uses_openai_config(self, monkeypatch, tmp_path):
        """OpenAI provider variants use the shared openai provider config."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.observer.set_provider(
            "openai",
            ProviderConfig(api_key_env="CUSTOM_OPENAI_KEY"),
        )
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)
        monkeypatch.setenv("CUSTOM_OPENAI_KEY", "my-custom-key")

        with patch.object(OpenAIProvider, "__init__", return_value=None) as mock_init:
            _provider_factory("openai-responses")
            call_kwargs = mock_init.call_args.kwargs
            assert call_kwargs["api_key"] == "my-custom-key"

    def test_openrouter_delegates_to_infer_provider(self, monkeypatch, tmp_path):
        """OpenRouter provider delegates to pydantic-ai's infer_provider."""
        test_settings = Settings(path=tmp_path / "config.json")
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        mock_provider = MagicMock()
        with patch.object(model_resolver.models, "infer_provider", return_value=mock_provider) as mock_infer:
            result = _provider_factory("openrouter")
            mock_infer.assert_called_once_with("openrouter")
            assert result is mock_provider

    def test_unknown_provider_delegates_to_infer_provider(self, monkeypatch, tmp_path):
        """Unknown providers delegate to pydantic-ai's infer_provider."""
        test_settings = Settings(path=tmp_path / "config.json")
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        mock_provider = MagicMock()
        with patch.object(model_resolver.models, "infer_provider", return_value=mock_provider) as mock_infer:
            result = _provider_factory("some-unknown-provider")
            mock_infer.assert_called_once_with("some-unknown-provider")
            assert result is mock_provider

    def test_openrouter_not_routed_to_openai_provider(self, monkeypatch, tmp_path):
        """OpenRouter is NOT treated as OpenAI-compatible."""
        test_settings = Settings(path=tmp_path / "config.json")
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        with patch.object(OpenAIProvider, "__init__", return_value=None) as mock_openai:
            with patch.object(model_resolver.models, "infer_provider", return_value=MagicMock()):
                _provider_factory("openrouter")
                mock_openai.assert_not_called()


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

        mock_model = MagicMock()
        with patch.object(model_resolver.models, "infer_model", return_value=mock_model) as mock_infer:
            with patch.object(model_resolver, "_provider_factory") as mock_factory:
                result = resolve_role_model("summary")

                mock_infer.assert_called_once()
                call_args = mock_infer.call_args
                assert call_args[0][0] == "anthropic:claude-test"
                assert call_args[1]["provider_factory"] is mock_factory
                assert result is mock_model

    def test_resolves_extraction_role(self, monkeypatch, tmp_path):
        """Extraction role resolves through model_refs."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.observer.model_refs = {
            "summary": "anthropic:claude-test",
            "extraction": "openai:gpt-4o",
        }
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        mock_model = MagicMock()
        with patch.object(model_resolver.models, "infer_model", return_value=mock_model) as mock_infer:
            with patch.object(model_resolver, "_provider_factory"):
                result = resolve_role_model("extraction")

                call_args = mock_infer.call_args
                assert call_args[0][0] == "openai:gpt-4o"
                assert result is mock_model

    def test_role_with_alias(self, monkeypatch, tmp_path):
        """Role model ref that is an alias gets resolved."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.models = {"fast": "anthropic:claude-fast"}
        test_settings.observer.model_refs = {
            "summary": "fast",
            "extraction": "anthropic:default",
        }
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        mock_model = MagicMock()
        with patch.object(model_resolver.models, "infer_model", return_value=mock_model) as mock_infer:
            with patch.object(model_resolver, "_provider_factory"):
                resolve_role_model("summary")

                call_args = mock_infer.call_args
                assert call_args[0][0] == "anthropic:claude-fast"

    def test_role_with_bare_model_alias(self, monkeypatch, tmp_path):
        """Role model ref alias to bare model gets normalized."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.models = {"fast": "gpt-4o-mini"}
        test_settings.observer.model_refs = {
            "summary": "fast",
            "extraction": "anthropic:default",
        }
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        mock_model = MagicMock()
        with patch.object(model_resolver.models, "infer_model", return_value=mock_model) as mock_infer:
            with patch.object(model_resolver, "_provider_factory"):
                resolve_role_model("summary")

                call_args = mock_infer.call_args
                assert call_args[0][0] == "openai:gpt-4o-mini"

    def test_uses_default_when_role_not_configured(self, monkeypatch, tmp_path):
        """Falls back to default when role not in model_refs."""
        test_settings = Settings(path=tmp_path / "config.json")
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        mock_model = MagicMock()
        with patch.object(model_resolver.models, "infer_model", return_value=mock_model) as mock_infer:
            with patch.object(model_resolver, "_provider_factory"):
                resolve_role_model("summary")

                call_args = mock_infer.call_args
                assert call_args[0][0] == "anthropic:claude-3-5-haiku-latest"

    def test_arbitrary_model_id_accepted(self, monkeypatch, tmp_path):
        """Arbitrary/nonexistent model IDs are accepted without validation."""
        test_settings = Settings(path=tmp_path / "config.json")
        test_settings.observer.model_refs = {
            "summary": "anthropic:completely-fake-model-xyz",
            "extraction": "anthropic:default",
        }
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        mock_model = MagicMock()
        with patch.object(model_resolver.models, "infer_model", return_value=mock_model) as mock_infer:
            with patch.object(model_resolver, "_provider_factory"):
                result = resolve_role_model("summary")

                call_args = mock_infer.call_args
                assert call_args[0][0] == "anthropic:completely-fake-model-xyz"
                assert result is mock_model


class TestProviderConfigIntegration:
    """Integration tests for provider config flow."""

    def test_default_provider_configs_used(self, monkeypatch, tmp_path):
        """Default provider configs are used when not overridden."""
        test_settings = Settings(path=tmp_path / "config.json")
        monkeypatch.setattr(model_resolver.settings_mod, "settings", test_settings)

        monkeypatch.setenv("OPENAI_API_KEY", "default-openai-key")

        with patch.object(OpenAIProvider, "__init__", return_value=None) as mock_init:
            _provider_factory("openai")
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
            _provider_factory("openai")
            call_kwargs = mock_init.call_args.kwargs
            assert call_kwargs["api_key"] == "custom-key"
