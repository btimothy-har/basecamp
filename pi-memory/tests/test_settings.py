import json
from pathlib import Path

import pytest
from pi_memory.settings import (
    INTERPRETATION_MODEL_ENV,
    InvalidInterpretationModelError,
    MissingInterpretationModelError,
    Settings,
)


def memory_settings(tmp_path: Path) -> Settings:
    return Settings(tmp_path / "memory" / "config.json")


@pytest.fixture(autouse=True)
def clear_memory_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(INTERPRETATION_MODEL_ENV, raising=False)


def test_defaults_report_missing_model_without_creating_file(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)

    assert settings.as_dict() == {"interpretation_model": None}
    assert not settings.path.exists()


def test_require_model_fails_clearly_when_unconfigured(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)

    with pytest.raises(MissingInterpretationModelError, match="interpretation_model is required"):
        settings.require_interpretation_model()


def test_file_model_persists(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)

    settings.update(interpretation_model="anthropic:claude-sonnet-4-6")

    assert json.loads(settings.path.read_text()) == {
        "interpretation_model": "anthropic:claude-sonnet-4-6",
    }
    assert Settings(settings.path).as_dict() == {
        "interpretation_model": "anthropic:claude-sonnet-4-6",
    }
    assert Settings(settings.path).require_interpretation_model() == "anthropic:claude-sonnet-4-6"


def test_env_override_wins_over_file_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = memory_settings(tmp_path)
    settings.update(interpretation_model="anthropic:file-model")

    monkeypatch.setenv(INTERPRETATION_MODEL_ENV, "openai:env-model")

    assert settings.as_dict() == {"interpretation_model": "openai:env-model"}
    assert settings.require_interpretation_model() == "openai:env-model"
    assert json.loads(settings.path.read_text()) == {
        "interpretation_model": "anthropic:file-model",
    }


def test_invalid_model_fails_clearly(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)

    with pytest.raises(InvalidInterpretationModelError, match="must be a non-empty string"):
        settings.update(interpretation_model="  ")


def test_invalid_env_model_fails_clearly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = memory_settings(tmp_path)
    monkeypatch.setenv(INTERPRETATION_MODEL_ENV, "  ")

    with pytest.raises(InvalidInterpretationModelError, match="must be a non-empty string"):
        settings.as_dict()


def test_clear_model_persists_absence(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)
    settings.update(interpretation_model="openai:any-model")

    settings.update(interpretation_model=None)

    assert settings.as_dict() == {"interpretation_model": None}
    assert json.loads(settings.path.read_text()) == {}


def test_update_removes_stale_interpreter_mode_key(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)
    settings.path.parent.mkdir(parents=True)
    settings.path.write_text(
        json.dumps(
            {
                "interpreter_mode": "deterministic",
                "interpretation_model": "anthropic:old-model",
            },
        ),
    )

    settings.update(interpretation_model="openai:new-model")

    assert json.loads(settings.path.read_text()) == {"interpretation_model": "openai:new-model"}
