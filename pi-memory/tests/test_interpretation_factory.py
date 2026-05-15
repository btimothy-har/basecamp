from __future__ import annotations

from pathlib import Path

import pi_memory.interpretation.factory as interpreter_factory
import pytest
from pi_memory.interpretation import DeterministicSessionInterpreter
from pi_memory.settings import INTERPRETATION_MODEL_ENV, INTERPRETER_MODE_ENV, Settings


def memory_settings(tmp_path: Path) -> Settings:
    return Settings(tmp_path / "memory" / "config.json")


@pytest.fixture(autouse=True)
def clear_memory_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(INTERPRETER_MODE_ENV, raising=False)
    monkeypatch.delenv(INTERPRETATION_MODEL_ENV, raising=False)


def test_factory_defaults_to_deterministic(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)

    interpreter = interpreter_factory.create_session_interpreter(settings)

    assert isinstance(interpreter, DeterministicSessionInterpreter)


def test_factory_returns_pydantic_ai_interpreter_with_configured_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = memory_settings(tmp_path)
    settings.update(
        interpreter_mode="pydantic-ai",
        interpretation_model="openai:gpt-4.1-mini",
    )
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
