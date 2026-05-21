from __future__ import annotations

import asyncio
from typing import Any

import pi_memory.infra.llm.pydantic_ai as llm_module
import pytest
from pi_memory.infra.llm import (
    create_pydantic_ai_agent,
    parse_model_reference,
    provider_from_model,
    pydantic_ai_model_metadata,
    resolve_pydantic_ai_model,
    run_pydantic_ai_agent,
    run_pydantic_ai_agent_sync,
)
from pydantic_ai.models.openrouter import OpenRouterModel


class DependencyMissingError(RuntimeError):
    pass


class RunResult:
    def __init__(self, output: Any) -> None:
        self.output = output


@pytest.mark.parametrize(
    ("model", "expected_provider", "expected_model_name"),
    [
        ("openai:gpt-5.5", "openai", "gpt-5.5"),
        ("anthropic:claude-opus-4-6", "anthropic", "claude-opus-4-6"),
        ("openrouter:openai/gpt-5.5", "openrouter", "openai/gpt-5.5"),
    ],
)
def test_parse_model_reference_and_metadata(
    model: str,
    expected_provider: str | None,
    expected_model_name: str,
) -> None:
    reference = parse_model_reference(model)

    assert reference.provider == expected_provider
    assert reference.model_name == expected_model_name
    assert reference.raw == model
    assert provider_from_model(model) == expected_provider
    assert pydantic_ai_model_metadata(model, mode="pydantic-ai", schema_version=7) == {
        "provider": expected_provider,
        "model": model,
        "mode": "pydantic-ai",
        "schema_version": 7,
    }


def test_parse_model_reference_and_metadata_for_plain_model_string() -> None:
    model = "gpt-5.5"
    reference = parse_model_reference(model)

    assert reference == llm_module.ModelReference(provider=None, model_name=model, raw=model)
    assert provider_from_model(model) is None
    assert pydantic_ai_model_metadata(model, mode="pydantic-ai", schema_version=9) == {
        "provider": None,
        "model": model,
        "mode": "pydantic-ai",
        "schema_version": 9,
    }


def test_create_pydantic_ai_agent_uses_factory_and_preserves_raw_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)

    calls: list[tuple[Any, type[Any]]] = []

    def fake_factory(model: Any, *, output_type: type[Any]) -> dict[str, Any]:
        calls.append((model, output_type))
        return {"model": model, "output_type": output_type}

    agent = create_pydantic_ai_agent(
        model="openrouter:openai/gpt-5.5",
        output_type=dict,
        agent_factory=fake_factory,
        dependency_error_factory=DependencyMissingError,
    )

    assert agent["model"] == "openrouter:openai/gpt-5.5"
    assert agent["output_type"] is dict
    assert calls == [("openrouter:openai/gpt-5.5", dict)]


def test_create_pydantic_ai_agent_raises_supplied_dependency_error_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_module, "PydanticAIAgent", None)

    with pytest.raises(DependencyMissingError):
        create_pydantic_ai_agent(
            model="openai:gpt-5.5",
            output_type=dict,
            agent_factory=None,
            dependency_error_factory=DependencyMissingError,
        )


def test_run_pydantic_ai_agent_sync_wrapper() -> None:
    class FakeAgent:
        def run_sync(self, prompt: str) -> RunResult:
            return RunResult(output=f"sync:{prompt}")

    result = run_pydantic_ai_agent_sync(FakeAgent(), "hello")

    assert isinstance(result, RunResult)
    assert result.output == "sync:hello"


def test_run_pydantic_ai_agent_async_wrapper() -> None:
    class AsyncRunAgent:
        async def run(self, prompt: str) -> RunResult:
            return RunResult(output=f"async:{prompt}")

    class SyncReturningRunAgent:
        def run(self, prompt: str) -> RunResult:
            return RunResult(output=f"sync-return:{prompt}")

    class RunSyncOnlyAgent:
        def run_sync(self, prompt: str) -> RunResult:
            return RunResult(output=f"fallback:{prompt}")

    async_result = asyncio.run(run_pydantic_ai_agent(AsyncRunAgent(), "a"))
    sync_return_result = asyncio.run(run_pydantic_ai_agent(SyncReturningRunAgent(), "b"))
    fallback_result = asyncio.run(run_pydantic_ai_agent(RunSyncOnlyAgent(), "c"))

    assert async_result.output == "async:a"
    assert sync_return_result.output == "sync-return:b"
    assert fallback_result.output == "fallback:c"


def test_resolve_openrouter_model_uses_custom_base_url_and_no_key_in_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_key = "fake-openrouter-api-key"
    custom_base_url = "https://openrouter.example.test/v1"
    monkeypatch.setenv("OPENROUTER_API_KEY", fake_key)
    monkeypatch.setenv("OPENROUTER_BASE_URL", custom_base_url)

    resolved = resolve_pydantic_ai_model("openrouter:openai/gpt-5.5")

    assert isinstance(resolved, OpenRouterModel)
    assert resolved.model_name == "openai/gpt-5.5"
    assert str(resolved.provider.client.base_url) == f"{custom_base_url}/"

    metadata = pydantic_ai_model_metadata(
        "openrouter:openai/gpt-5.5",
        mode="pydantic-ai",
        schema_version=1,
    )
    assert fake_key not in str(metadata)


def test_resolve_openrouter_model_with_custom_base_url_missing_openrouter_key_returns_raw_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-api-key")

    resolved = resolve_pydantic_ai_model("openrouter:openai/gpt-5.5")

    assert resolved == "openrouter:openai/gpt-5.5"
