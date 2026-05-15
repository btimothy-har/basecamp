import json
from pathlib import Path

import pytest
from pi_memory.settings import (
    INTERPRETATION_MODEL_ENV,
    INTERPRETER_MODE_ENV,
    InvalidInterpretationModelError,
    InvalidInterpreterModeError,
    MissingInterpretationModelError,
    Settings,
)


def memory_settings(tmp_path: Path) -> Settings:
    return Settings(tmp_path / "memory" / "config.json")


@pytest.fixture(autouse=True)
def clear_memory_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(INTERPRETER_MODE_ENV, raising=False)
    monkeypatch.delenv(INTERPRETATION_MODEL_ENV, raising=False)


def test_defaults_resolve_to_deterministic(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)

    assert settings.as_dict() == {
        "interpreter_mode": "deterministic",
        "interpretation_model": None,
    }
    assert not settings.path.exists()


def test_file_settings_persist(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)

    settings.update(
        interpreter_mode="pydantic-ai",
        interpretation_model="anthropic:claude-sonnet-4-6",
    )

    assert json.loads(settings.path.read_text()) == {
        "interpreter_mode": "pydantic-ai",
        "interpretation_model": "anthropic:claude-sonnet-4-6",
    }
    assert Settings(settings.path).as_dict() == {
        "interpreter_mode": "pydantic-ai",
        "interpretation_model": "anthropic:claude-sonnet-4-6",
    }


def test_env_overrides_win_over_file_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = memory_settings(tmp_path)
    settings.update(
        interpreter_mode="pydantic-ai",
        interpretation_model="anthropic:file-model",
    )

    monkeypatch.setenv(INTERPRETER_MODE_ENV, "deterministic")
    monkeypatch.setenv(INTERPRETATION_MODEL_ENV, "openai:env-model")

    assert settings.as_dict() == {
        "interpreter_mode": "deterministic",
        "interpretation_model": "openai:env-model",
    }
    assert json.loads(settings.path.read_text()) == {
        "interpreter_mode": "pydantic-ai",
        "interpretation_model": "anthropic:file-model",
    }


def test_pydantic_ai_effective_mode_requires_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = memory_settings(tmp_path)
    monkeypatch.setenv(INTERPRETER_MODE_ENV, "pydantic-ai")

    with pytest.raises(MissingInterpretationModelError, match="interpretation_model is required"):
        settings.as_dict()


def test_invalid_mode_fails_clearly(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)

    with pytest.raises(InvalidInterpreterModeError, match="Invalid interpreter mode"):
        settings.update(interpreter_mode="anthropic")


def test_invalid_model_fails_clearly(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)

    with pytest.raises(InvalidInterpretationModelError, match="must be a non-empty string"):
        settings.update(interpretation_model="  ")


def test_cannot_persist_pydantic_ai_without_model(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)

    with pytest.raises(MissingInterpretationModelError, match="interpretation_model is required"):
        settings.update(interpreter_mode="pydantic-ai")

    assert not settings.path.exists()


def test_clear_model_persists_absence_for_deterministic_mode(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)
    settings.update(interpretation_model="openai:any-model")

    settings.update(interpretation_model=None)

    assert settings.as_dict() == {
        "interpreter_mode": "deterministic",
        "interpretation_model": None,
    }
    assert json.loads(settings.path.read_text()) == {"interpreter_mode": "deterministic"}
