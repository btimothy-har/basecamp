"""Shared PydanticAI model and agent infrastructure."""

from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlparse

try:
    from pydantic_ai import Agent as PydanticAIAgent
except ImportError:
    PydanticAIAgent = None

try:
    from pydantic_ai.models import parse_model_id as pydantic_ai_parse_model_id
except ImportError:
    pydantic_ai_parse_model_id = None

try:
    from openai import AsyncOpenAI
    from pydantic_ai.models.openrouter import OpenRouterModel
    from pydantic_ai.providers.openrouter import OpenRouterProvider
except ImportError:
    AsyncOpenAI = None
    OpenRouterModel = None
    OpenRouterProvider = None

AgentFactory = Callable[..., Any]

_OPENROUTER_BASE_URL_ERROR = (
    "OPENROUTER_BASE_URL must be a valid https URL without embedded credentials"
)


@dataclass(frozen=True)
class ModelReference:
    """Parsed model reference parts."""

    provider: str | None
    model_name: str
    raw: str


def parse_model_reference(model: str) -> ModelReference:
    """Parse a user-facing PydanticAI model reference."""
    provider, separator, model_name = model.partition(":")
    if not separator:
        return ModelReference(provider=None, model_name=model, raw=model)

    if pydantic_ai_parse_model_id is not None:
        parsed_provider, parsed_model_name = pydantic_ai_parse_model_id(model)
        return ModelReference(provider=parsed_provider, model_name=parsed_model_name, raw=model)

    return ModelReference(provider=provider, model_name=model_name, raw=model)


def provider_from_model(model: str) -> str | None:
    """Return the parsed provider prefix, if present."""
    return parse_model_reference(model).provider


def pydantic_ai_model_metadata(model: str, *, mode: str, schema_version: int) -> Mapping[str, Any]:
    """Build provider/model metadata for persisted model usage context."""
    return {
        "provider": provider_from_model(model),
        "model": model,
        "mode": mode,
        "schema_version": schema_version,
    }


def resolve_pydantic_ai_model(model: str) -> str | Any:
    """Resolve a model reference, returning raw strings unless special handling is needed."""
    reference = parse_model_reference(model)
    openrouter_base_url = os.getenv("OPENROUTER_BASE_URL")
    if reference.provider != "openrouter" or not openrouter_base_url:
        return model

    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_api_key:
        return model

    _validate_openrouter_base_url(openrouter_base_url)

    if AsyncOpenAI is None or OpenRouterModel is None or OpenRouterProvider is None:
        return model

    openrouter_client = AsyncOpenAI(
        api_key=openrouter_api_key,
        base_url=openrouter_base_url,
    )
    provider = OpenRouterProvider(openai_client=openrouter_client)
    return OpenRouterModel(reference.model_name, provider=provider)


def create_pydantic_ai_agent(
    model: str,
    output_type: type[Any],
    agent_factory: AgentFactory | None = None,
    dependency_error_factory: Callable[[], Exception] = RuntimeError,
) -> Any:
    """Create a PydanticAI agent, resolving provider-specific model overrides."""
    factory = agent_factory if agent_factory is not None else _pydantic_ai_agent_factory(dependency_error_factory)
    resolved_model = resolve_pydantic_ai_model(model)
    return factory(resolved_model, output_type=output_type)


def run_pydantic_ai_agent_sync(agent: Any, prompt: str) -> Any:
    """Run a PydanticAI-compatible agent synchronously."""
    return agent.run_sync(prompt)


async def run_pydantic_ai_agent(agent: Any, prompt: str) -> Any:
    """Run a PydanticAI-compatible agent, supporting async and sync test doubles."""
    run = getattr(agent, "run", None)
    if run is None:
        return await asyncio.to_thread(agent.run_sync, prompt)
    result = run(prompt)
    if inspect.isawaitable(result):
        return await result
    return result


def _validate_openrouter_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(_OPENROUTER_BASE_URL_ERROR)


def _pydantic_ai_agent_factory(dependency_error_factory: Callable[[], Exception]) -> AgentFactory:
    if PydanticAIAgent is None:
        raise dependency_error_factory()
    return cast(AgentFactory, PydanticAIAgent)
