"""Resolve observer LLM model refs into pydantic-ai models."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal, cast

from basecamp import settings as settings_mod
from basecamp.settings import ProviderConfig
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from observer.exceptions import InvalidModelRefError

if TYPE_CHECKING:
    from pydantic_ai.models import Model

ProviderName = Literal["openai", "anthropic", "openrouter"]
_SUPPORTED_PROVIDERS = frozenset({"openai", "anthropic", "openrouter"})
_LEGACY_OPENAI_PROVIDERS = frozenset({"openai-chat", "openai-responses"})


def parse_model_ref(model_ref: str) -> tuple[ProviderName, str]:
    """Parse an explicit observer model ref."""
    ref = model_ref.strip()
    if not ref:
        raise InvalidModelRefError(model_ref, "model reference cannot be empty")

    provider, separator, model_id = ref.partition(":")
    provider = provider.strip()
    model_id = model_id.strip()

    if not separator:
        raise InvalidModelRefError(
            model_ref,
            "model reference must use explicit 'provider:model_id' format. "
            f"Supported providers: {_provider_names()}",
        )

    if not provider:
        raise InvalidModelRefError(model_ref, "provider cannot be empty")

    if not model_id:
        raise InvalidModelRefError(model_ref, "model_id cannot be empty")

    if provider in _LEGACY_OPENAI_PROVIDERS:
        raise InvalidModelRefError(
            model_ref,
            f"'{provider}' provider is not supported. Use 'openai:{model_id}' instead",
        )

    if provider not in _SUPPORTED_PROVIDERS:
        raise InvalidModelRefError(
            model_ref,
            f"unsupported provider '{provider}'. Supported providers: {_provider_names()}",
        )

    return cast(ProviderName, provider), model_id


def resolve_model_ref(model_ref: str) -> tuple[ProviderName, str]:
    """Resolve one model alias, then parse the target model ref."""
    aliases = settings_mod.settings.models
    resolved = aliases.get(model_ref, model_ref)
    return parse_model_ref(resolved)


def _provider_names() -> str:
    return ", ".join(sorted(_SUPPORTED_PROVIDERS))


def _get_env_value(env_name: str | None) -> str | None:
    if not env_name:
        return None
    value = os.getenv(env_name)
    return value if value else None


def _provider_config(provider_name: ProviderName) -> ProviderConfig | None:
    return settings_mod.settings.observer.provider_configs.get(provider_name)


class ObserverOpenRouterProvider(OpenRouterProvider):
    """OpenRouter provider with observer-configured base URL support."""

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None) -> None:
        self._observer_base_url = base_url
        super().__init__(api_key=api_key)

    @property
    def base_url(self) -> str:
        return self._observer_base_url or super().base_url


def _create_openai_provider(config: ProviderConfig | None) -> OpenAIProvider:
    api_key = _get_env_value(config.api_key_env) if config else None
    base_url = _get_env_value(config.base_url_env) if config else None
    return OpenAIProvider(api_key=api_key, base_url=base_url)


def _create_anthropic_provider(config: ProviderConfig | None) -> AnthropicProvider:
    api_key = _get_env_value(config.api_key_env) if config else None
    base_url = _get_env_value(config.base_url_env) if config else None
    return AnthropicProvider(api_key=api_key, base_url=base_url)


def _create_openrouter_provider(config: ProviderConfig | None) -> ObserverOpenRouterProvider:
    api_key = _get_env_value(config.api_key_env) if config else None
    base_url = _get_env_value(config.base_url_env) if config else None
    return ObserverOpenRouterProvider(api_key=api_key, base_url=base_url)


def _create_model(provider: ProviderName, model_id: str) -> Model:
    config = _provider_config(provider)

    if provider == "openai":
        return OpenAIResponsesModel(model_id, provider=_create_openai_provider(config))

    if provider == "anthropic":
        return AnthropicModel(model_id, provider=_create_anthropic_provider(config))

    if provider == "openrouter":
        return OpenRouterModel(model_id, provider=_create_openrouter_provider(config))

    raise InvalidModelRefError(f"{provider}:{model_id}", f"unsupported provider '{provider}'")


def resolve_role_model(role: Literal["summary", "extraction"]) -> Model:
    """Resolve a pydantic-ai model for an observer role."""
    raw_ref = settings_mod.settings.observer.model_refs[role]
    provider, model_id = resolve_model_ref(raw_ref)
    return _create_model(provider, model_id)
