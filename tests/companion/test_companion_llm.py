"""Tests for companion LLM helpers."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import basecamp.companion.llm as llm_module
from basecamp.companion.llm import (
    ModelReference,
    create_pydantic_ai_agent,
    parse_model_reference,
    provider_from_model,
    pydantic_ai_model_metadata,
    resolve_pydantic_ai_model,
    run_pydantic_ai_agent,
    run_pydantic_ai_agent_sync,
)


@pytest.mark.parametrize(
    ("model", "expected_provider", "expected_name"),
    [
        ("openai:gpt-5", "openai", "gpt-5"),
        ("anthropic:claude-haiku-4-5", "anthropic", "claude-haiku-4-5"),
        ("openrouter:anthropic/claude-sonnet-4", "openrouter", "anthropic/claude-sonnet-4"),
    ],
)
def test_parse_model_reference_provider_forms(
    model: str,
    expected_provider: str,
    expected_name: str,
) -> None:
    parsed = parse_model_reference(model)

    assert parsed == ModelReference(
        provider=expected_provider,
        model_name=expected_name,
        raw=model,
    )


def test_parse_model_reference_plain_string() -> None:
    parsed = parse_model_reference("gpt-5")

    assert parsed == ModelReference(provider=None, model_name="gpt-5", raw="gpt-5")
    assert provider_from_model("gpt-5") is None


def test_pydantic_ai_model_metadata() -> None:
    metadata = pydantic_ai_model_metadata(
        "anthropic:claude-haiku-4-5",
        mode="dashboard",
        schema_version=1,
    )

    assert metadata == {
        "provider": "anthropic",
        "model": "anthropic:claude-haiku-4-5",
        "mode": "dashboard",
        "schema_version": 1,
    }


def test_create_pydantic_ai_agent_uses_factory_and_preserves_model() -> None:
    seen: dict[str, object] = {}

    def fake_factory(model: object, *, output_type: type[object]) -> object:
        seen["model"] = model
        seen["output_type"] = output_type
        return "agent"

    agent = create_pydantic_ai_agent(
        model="anthropic:claude-haiku-4-5",
        output_type=dict,
        agent_factory=fake_factory,
    )

    assert agent == "agent"
    assert seen == {"model": "anthropic:claude-haiku-4-5", "output_type": dict}


def test_create_pydantic_ai_agent_dependency_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class MissingDependencyError(RuntimeError):
        pass

    monkeypatch.setattr(llm_module, "PydanticAIAgent", None)

    with pytest.raises(MissingDependencyError):
        create_pydantic_ai_agent(
            model="anthropic:claude-haiku-4-5",
            output_type=dict,
            dependency_error_factory=MissingDependencyError,
        )


def test_run_pydantic_ai_agent_sync_wrapper() -> None:
    @dataclass
    class FakeAgent:
        def run_sync(self, prompt: str) -> str:
            return f"sync:{prompt}"

    assert run_pydantic_ai_agent_sync(FakeAgent(), "hello") == "sync:hello"


@pytest.mark.asyncio
async def test_run_pydantic_ai_agent_wrapper_prefers_async_run() -> None:
    @dataclass
    class FakeAgent:
        async def run(self, prompt: str) -> str:
            return f"async:{prompt}"

    result = await run_pydantic_ai_agent(FakeAgent(), "hello")

    assert result == "async:hello"


@pytest.mark.asyncio
async def test_run_pydantic_ai_agent_wrapper_falls_back_to_sync() -> None:
    @dataclass
    class FakeAgent:
        def run_sync(self, prompt: str) -> str:
            return f"sync:{prompt}"

    result = await run_pydantic_ai_agent(FakeAgent(), "hello")

    assert result == "sync:hello"


def test_resolve_openrouter_custom_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncOpenAI:
        def __init__(self, *, api_key: str, base_url: str) -> None:
            self.api_key = api_key
            self.base_url = base_url
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    class FakeOpenRouterProvider:
        def __init__(self, *, openai_client: FakeAsyncOpenAI) -> None:
            self.openai_client = openai_client
            captured["provider_client"] = openai_client

    class FakeOpenAIChatModel:
        def __init__(self, model_name: str, *, provider: FakeOpenRouterProvider) -> None:
            self.model_name = model_name
            self.provider = provider
            captured["model_name"] = model_name
            captured["provider"] = provider

    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.example/api/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-key")
    monkeypatch.setattr(llm_module, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setattr(llm_module, "OpenRouterProvider", FakeOpenRouterProvider)
    monkeypatch.setattr(llm_module, "OpenAIChatModel", FakeOpenAIChatModel)

    resolved = resolve_pydantic_ai_model("openrouter:anthropic/claude-sonnet-4")

    assert isinstance(resolved, FakeOpenAIChatModel)
    assert resolved.model_name == "anthropic/claude-sonnet-4"
    assert captured["api_key"] == "secret-key"
    assert captured["base_url"] == "https://openrouter.example/api/v1"
    assert isinstance(resolved.provider, FakeOpenRouterProvider)
    assert isinstance(resolved.provider.openai_client, FakeAsyncOpenAI)
    assert captured["provider"] is resolved.provider
    assert resolved.provider.openai_client is captured["provider_client"]
    assert captured["model_name"] == "anthropic/claude-sonnet-4"


def test_resolve_openrouter_missing_key_returns_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.example/api/v1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    resolved = resolve_pydantic_ai_model("openrouter:anthropic/claude-sonnet-4")

    assert resolved == "openrouter:anthropic/claude-sonnet-4"


def test_resolve_openrouter_unsafe_base_url_rejected_without_secret_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsafe_url = "https://user:secret@example.com/api/v1"
    monkeypatch.setenv("OPENROUTER_BASE_URL", unsafe_url)
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-key")

    with pytest.raises(ValueError, match=llm_module._OPENROUTER_BASE_URL_ERROR) as excinfo:
        resolve_pydantic_ai_model("openrouter:anthropic/claude-sonnet-4")

    assert "secret" not in str(excinfo.value)
    assert "user:secret" not in str(excinfo.value)
    assert "secret-key" not in str(excinfo.value)
