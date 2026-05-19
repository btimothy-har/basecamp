from __future__ import annotations

from pathlib import Path

import pi_memory.quality.factory as quality_factory
import pytest
from pi_memory.settings import (
    INTERPRETATION_MODEL_ENV,
    QUALITY_MODEL_ENV,
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
    monkeypatch.delenv(QUALITY_MODEL_ENV, raising=False)


@pytest.fixture
def fake_assessor(monkeypatch: pytest.MonkeyPatch) -> type:
    class FakePydanticAIQualityAssessor:
        def __init__(self, model: str) -> None:
            self.model = model

    monkeypatch.setattr(
        quality_factory,
        "PydanticAIQualityAssessor",
        FakePydanticAIQualityAssessor,
    )
    return FakePydanticAIQualityAssessor


def test_factory_requires_quality_model_fallback(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)

    with pytest.raises(MissingInterpretationModelError, match="interpretation_model is required"):
        quality_factory.create_quality_assessor(settings)


def test_factory_uses_explicit_quality_model(tmp_path: Path, fake_assessor: type) -> None:
    settings = memory_settings(tmp_path)
    settings.update(
        interpretation_model="openai:interpretation-model",
        tool_summary_model="openai:summary-model",
        quality_model="anthropic:quality-model",
    )

    assessor = quality_factory.create_quality_assessor(settings)

    assert isinstance(assessor, fake_assessor)
    assert assessor.model == "anthropic:quality-model"


def test_factory_falls_back_to_tool_summary_model(tmp_path: Path, fake_assessor: type) -> None:
    settings = memory_settings(tmp_path)
    settings.update(
        interpretation_model="openai:interpretation-model",
        tool_summary_model="anthropic:summary-model",
    )

    assessor = quality_factory.create_quality_assessor(settings)

    assert isinstance(assessor, fake_assessor)
    assert assessor.model == "anthropic:summary-model"


def test_factory_falls_back_to_interpretation_model(tmp_path: Path, fake_assessor: type) -> None:
    settings = memory_settings(tmp_path)
    settings.update(interpretation_model="openai:interpretation-model")

    assessor = quality_factory.create_quality_assessor(settings)

    assert isinstance(assessor, fake_assessor)
    assert assessor.model == "openai:interpretation-model"


def test_factory_uses_quality_environment_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_assessor: type,
) -> None:
    settings = memory_settings(tmp_path)
    settings.update(
        interpretation_model="openai:interpretation-model",
        tool_summary_model="anthropic:summary-model",
        quality_model="anthropic:file-quality-model",
    )
    monkeypatch.setenv(QUALITY_MODEL_ENV, "openai:env-quality-model")

    assessor = quality_factory.create_quality_assessor(settings)

    assert isinstance(assessor, fake_assessor)
    assert assessor.model == "openai:env-quality-model"
