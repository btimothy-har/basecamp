"""Model resolver for observer LLM agents.

Resolves model references through alias maps and constructs pydantic-ai
Model instances with custom provider configuration.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Literal

from basecamp import settings as settings_mod
from basecamp.settings import ProviderConfig
from pydantic_ai import models
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

if TYPE_CHECKING:
    from pydantic_ai.models import Model
    from pydantic_ai.providers import Provider

_OPENAI_PROVIDERS = frozenset({"openai", "openai-chat", "openai-responses"})
_CUSTOM_PROVIDERS = frozenset({*_OPENAI_PROVIDERS, "anthropic"})


def normalize_model_ref(model_ref: str) -> str:
    """Apply observer's default OpenAI provider prefix."""
    if ":" in model_ref:
        return model_ref
    return f"openai:{model_ref}"


def resolve_model_ref(model_ref: str) -> str:
    """Resolve one model alias and apply provider normalization."""
    aliases = settings_mod.settings.models
    resolved = aliases.get(model_ref, model_ref)
    return normalize_model_ref(resolved)


def _get_env_value(env_name: str | None) -> str | None:
    """Get environment variable value, returning None if not set or empty."""
    if not env_name:
        return None
    value = os.getenv(env_name)
    return value if value else None


def _create_provider(provider_name: str, config: ProviderConfig | None) -> Provider[Any]:
    """Create a configured pydantic-ai provider."""
    api_key = _get_env_value(config.api_key_env) if config else None
    base_url = _get_env_value(config.base_url_env) if config else None

    if provider_name in ("openai", "openai-chat", "openai-responses"):
        return OpenAIProvider(api_key=api_key, base_url=base_url)

    if provider_name == "anthropic":
        return AnthropicProvider(api_key=api_key, base_url=base_url)

    return models.infer_provider(provider_name)


def _provider_config(provider_name: str) -> ProviderConfig | None:
    configs = settings_mod.settings.observer.provider_configs
    if provider_name in _OPENAI_PROVIDERS:
        return configs.get(provider_name) or configs.get("openai")
    return configs.get(provider_name)


def _provider_factory(provider_name: str) -> Provider[Any]:
    """Provider factory for use with infer_model."""
    if provider_name in _CUSTOM_PROVIDERS:
        return _create_provider(provider_name, _provider_config(provider_name))

    return models.infer_provider(provider_name)


def resolve_role_model(role: Literal["summary", "extraction"]) -> Model:
    """Resolve a pydantic-ai model for an observer role."""
    raw_ref = settings_mod.settings.observer.model_refs[role]
    resolved = resolve_model_ref(raw_ref)
    return models.infer_model(resolved, provider_factory=_provider_factory)
