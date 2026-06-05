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
    from pydantic_ai.models.openai import OpenAIChatModel
except ImportError:
    OpenAIChatModel = None

try:
    from pydantic_ai.providers.openrouter import OpenRouterProvider
except ImportError:
    OpenRouterProvider = None

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

AgentFactory = Callable[..., Any]
_OPENROUTER_BASE_URL_ERROR = "OPENROUTER_BASE_URL must be a valid https URL without embedded credentials"


@dataclass(frozen=True)
class ModelReference:
    provider: str | None
    model_name: str
    raw: str


def parse_model_reference(model: str) -> ModelReference:
    provider, separator, model_name = model.partition(":")
    if not separator:
        return ModelReference(provider=None, model_name=model, raw=model)

    if pydantic_ai_parse_model_id is not None:
        parsed_provider, parsed_model_name = pydantic_ai_parse_model_id(model)
        return ModelReference(provider=parsed_provider, model_name=parsed_model_name, raw=model)

    return ModelReference(provider=provider, model_name=model_name, raw=model)


def provider_from_model(model: str) -> str | None:
    return parse_model_reference(model).provider


def pydantic_ai_model_metadata(model: str, *, mode: str, schema_version: int) -> Mapping[str, Any]:
    return {
        "provider": provider_from_model(model),
        "model": model,
        "mode": mode,
        "schema_version": schema_version,
    }


def resolve_pydantic_ai_model(model: str) -> str | Any:
    reference = parse_model_reference(model)
    openrouter_base_url = os.getenv("OPENROUTER_BASE_URL")
    if reference.provider != "openrouter" or not openrouter_base_url:
        return model

    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_api_key:
        return model

    _validate_openrouter_base_url(openrouter_base_url)

    if OpenAIChatModel is None or OpenRouterProvider is None or AsyncOpenAI is None:
        return model

    return OpenAIChatModel(
        reference.model_name,
        provider=OpenRouterProvider(
            openai_client=AsyncOpenAI(api_key=openrouter_api_key, base_url=openrouter_base_url)
        ),
    )


def create_pydantic_ai_agent(
    model: str,
    output_type: type[Any],
    agent_factory: AgentFactory | None = None,
    dependency_error_factory: Callable[[], Exception] = RuntimeError,
) -> Any:
    factory = agent_factory if agent_factory is not None else _pydantic_ai_agent_factory(dependency_error_factory)
    resolved_model = resolve_pydantic_ai_model(model)
    return factory(resolved_model, output_type=output_type)


def run_pydantic_ai_agent_sync(agent: Any, prompt: str) -> Any:
    return agent.run_sync(prompt)


async def run_pydantic_ai_agent(agent: Any, prompt: str) -> Any:
    run = getattr(agent, "run", None)
    if run is None:
        return await asyncio.to_thread(agent.run_sync, prompt)

    result = run(prompt)
    if inspect.isawaitable(result):
        return await result
    return result


def _validate_openrouter_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname or "@" in parsed.netloc:
        raise ValueError(_OPENROUTER_BASE_URL_ERROR)


def _pydantic_ai_agent_factory(
    dependency_error_factory: Callable[[], Exception],
) -> AgentFactory:
    if PydanticAIAgent is None:
        raise dependency_error_factory()
    return cast(AgentFactory, PydanticAIAgent)
