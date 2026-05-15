from __future__ import annotations

from pathlib import Path

import pi_memory.interpretation.factory as interpreter_factory
import pytest
from pi_memory.settings import (
    INTERPRETATION_MODEL_ENV,
    TOOL_SUMMARY_MODEL_ENV,
    MissingInterpretationModelError,
    Settings,
)


def memory_settings(tmp_path: Path) -> Settings:
    return Settings(tmp_path / "memory" / "config.json")


@pytest.fixture(autouse=True)
def clear_memory_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(INTERPRETATION_MODEL_ENV, raising=False)
    monkeypatch.delenv(TOOL_SUMMARY_MODEL_ENV, raising=False)


def test_factory_requires_interpretation_model(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)

    with pytest.raises(MissingInterpretationModelError, match="interpretation_model is required"):
        interpreter_factory.create_session_interpreter(settings)


def test_factory_returns_pydantic_ai_interpreter_with_configured_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = memory_settings(tmp_path)
    settings.update(interpretation_model="openai:gpt-4.1-mini")
    calls: list[str] = []

    class FakePydanticAISessionInterpreter:
        def __init__(self, model: str) -> None:
            calls.append(model)
            self.model = model

    monkeypatch.setattr(
        interpreter_factory,
        "PydanticAISessionInterpreter",
        FakePydanticAISessionInterpreter,
    )

    interpreter = interpreter_factory.create_session_interpreter(settings)

    assert isinstance(interpreter, FakePydanticAISessionInterpreter)
    assert interpreter.model == "openai:gpt-4.1-mini"
    assert calls == ["openai:gpt-4.1-mini"]


def test_factory_returns_pydantic_ai_tool_summarizer_with_configured_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = memory_settings(tmp_path)
    settings.update(
        interpretation_model="openai:gpt-4.1-mini",
        tool_summary_model="anthropic:claude-haiku-4-5",
    )
    calls: list[str] = []

    class FakePydanticAIToolActivitySummarizer:
        def __init__(self, model: str) -> None:
            calls.append(model)
            self.model = model

    monkeypatch.setattr(
        interpreter_factory,
        "PydanticAIToolActivitySummarizer",
        FakePydanticAIToolActivitySummarizer,
    )

    summarizer = interpreter_factory.create_tool_activity_summarizer(settings)

    assert isinstance(summarizer, FakePydanticAIToolActivitySummarizer)
    assert summarizer.model == "anthropic:claude-haiku-4-5"
    assert calls == ["anthropic:claude-haiku-4-5"]


def test_tool_summarizer_factory_falls_back_to_interpretation_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = memory_settings(tmp_path)
    settings.update(interpretation_model="openai:gpt-4.1-mini")

    class FakePydanticAIToolActivitySummarizer:
        def __init__(self, model: str) -> None:
            self.model = model

    monkeypatch.setattr(
        interpreter_factory,
        "PydanticAIToolActivitySummarizer",
        FakePydanticAIToolActivitySummarizer,
    )

    summarizer = interpreter_factory.create_tool_activity_summarizer(settings)

    assert isinstance(summarizer, FakePydanticAIToolActivitySummarizer)
    assert summarizer.model == "openai:gpt-4.1-mini"


def test_factory_uses_environment_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = memory_settings(tmp_path)
    settings.update(interpretation_model="anthropic:file-model")
    monkeypatch.setenv(INTERPRETATION_MODEL_ENV, "openai:env-model")

    class FakePydanticAISessionInterpreter:
        def __init__(self, model: str) -> None:
            self.model = model

    monkeypatch.setattr(
        interpreter_factory,
        "PydanticAISessionInterpreter",
        FakePydanticAISessionInterpreter,
    )

    interpreter = interpreter_factory.create_session_interpreter(settings)

    assert isinstance(interpreter, FakePydanticAISessionInterpreter)
    assert interpreter.model == "openai:env-model"
