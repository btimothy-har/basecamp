import json
from pathlib import Path

import pi_memory.settings as settings_module
import pytest
from pi_memory.settings import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_TOOL_SUMMARY_CONCURRENCY,
    EMBEDDING_MODEL_ENV,
    INTERPRETATION_MODEL_ENV,
    QUALITY_MODEL_ENV,
    TOOL_SUMMARY_CONCURRENCY_ENV,
    TOOL_SUMMARY_MODEL_ENV,
    InvalidEmbeddingModelError,
    InvalidInterpretationModelError,
    InvalidToolSummaryConcurrencyError,
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
    monkeypatch.delenv(EMBEDDING_MODEL_ENV, raising=False)
    monkeypatch.delenv(TOOL_SUMMARY_CONCURRENCY_ENV, raising=False)


def test_defaults_report_missing_model_without_creating_file(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)

    assert settings.as_dict() == {
        "interpretation_model": None,
        "tool_summary_model": None,
        "quality_model": None,
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        "tool_summary_concurrency": DEFAULT_TOOL_SUMMARY_CONCURRENCY,
    }
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
        "tool_summary_model": None,
        "quality_model": None,
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        "tool_summary_concurrency": DEFAULT_TOOL_SUMMARY_CONCURRENCY,
    }
    assert Settings(settings.path).require_interpretation_model() == "anthropic:claude-sonnet-4-6"


def test_file_write_handles_partial_os_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = memory_settings(tmp_path)
    writes = []
    real_write = settings_module.os.write

    def partial_write(fd: int, data: bytes | bytearray | memoryview) -> int:
        content = bytes(data)
        size = max(1, len(content) // 2)
        writes.append(size)
        return real_write(fd, content[:size])

    monkeypatch.setattr(settings_module.os, "write", partial_write)

    settings.update(interpretation_model="anthropic:claude-sonnet-4-6")

    assert len(writes) > 1
    assert json.loads(settings.path.read_text()) == {
        "interpretation_model": "anthropic:claude-sonnet-4-6",
    }


def test_env_override_wins_over_file_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = memory_settings(tmp_path)
    settings.update(interpretation_model="anthropic:file-model")

    monkeypatch.setenv(INTERPRETATION_MODEL_ENV, "openai:env-model")

    assert settings.as_dict() == {
        "interpretation_model": "openai:env-model",
        "tool_summary_model": None,
        "quality_model": None,
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        "tool_summary_concurrency": DEFAULT_TOOL_SUMMARY_CONCURRENCY,
    }
    assert settings.require_interpretation_model() == "openai:env-model"
    assert json.loads(settings.path.read_text()) == {
        "interpretation_model": "anthropic:file-model",
    }


def test_tool_summary_model_persists_and_env_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = memory_settings(tmp_path)

    settings.update(
        interpretation_model="anthropic:claude-sonnet-4-6",
        tool_summary_model="anthropic:claude-haiku-4-5",
    )

    assert settings.require_tool_summary_model() == "anthropic:claude-haiku-4-5"
    monkeypatch.setenv(TOOL_SUMMARY_MODEL_ENV, "openai:fast-summary-model")
    assert settings.as_dict() == {
        "interpretation_model": "anthropic:claude-sonnet-4-6",
        "tool_summary_model": "openai:fast-summary-model",
        "quality_model": None,
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        "tool_summary_concurrency": DEFAULT_TOOL_SUMMARY_CONCURRENCY,
    }
    assert settings.require_tool_summary_model() == "openai:fast-summary-model"
    assert json.loads(settings.path.read_text()) == {
        "interpretation_model": "anthropic:claude-sonnet-4-6",
        "tool_summary_model": "anthropic:claude-haiku-4-5",
    }


def test_tool_summary_model_falls_back_to_interpretation_model(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)
    settings.update(interpretation_model="anthropic:claude-sonnet-4-6")

    assert settings.tool_summary_model is None
    assert settings.require_tool_summary_model() == "anthropic:claude-sonnet-4-6"


def test_quality_model_persists_and_env_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = memory_settings(tmp_path)

    settings.update(
        interpretation_model="anthropic:claude-sonnet-4-6",
        quality_model="anthropic:claude-opus-4-1",
    )

    assert settings.quality_model == "anthropic:claude-opus-4-1"
    assert settings.require_quality_model() == "anthropic:claude-opus-4-1"
    monkeypatch.setenv(QUALITY_MODEL_ENV, "openai:quality-env-model")
    assert settings.as_dict() == {
        "interpretation_model": "anthropic:claude-sonnet-4-6",
        "tool_summary_model": None,
        "quality_model": "openai:quality-env-model",
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        "tool_summary_concurrency": DEFAULT_TOOL_SUMMARY_CONCURRENCY,
    }
    assert settings.require_quality_model() == "openai:quality-env-model"
    assert json.loads(settings.path.read_text()) == {
        "interpretation_model": "anthropic:claude-sonnet-4-6",
        "quality_model": "anthropic:claude-opus-4-1",
    }


def test_quality_model_fallback_chain(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)
    settings.update(
        interpretation_model="anthropic:interpretation-model",
        tool_summary_model="anthropic:summary-model",
    )

    assert settings.require_quality_model() == "anthropic:summary-model"

    settings.update(quality_model="anthropic:quality-model")

    assert settings.require_quality_model() == "anthropic:quality-model"

    settings.update(quality_model=None, tool_summary_model=None)

    assert settings.require_quality_model() == "anthropic:interpretation-model"


def test_require_quality_model_fails_clearly_when_unconfigured(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)

    with pytest.raises(MissingInterpretationModelError, match="interpretation_model is required"):
        settings.require_quality_model()


def test_embedding_model_persists_and_env_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = memory_settings(tmp_path)

    settings.update(embedding_model="custom-embedding-model")

    assert settings.embedding_model == "custom-embedding-model"
    monkeypatch.setenv(EMBEDDING_MODEL_ENV, "env-embedding-model")
    assert settings.embedding_model == "env-embedding-model"
    assert settings.as_dict()["embedding_model"] == "env-embedding-model"
    assert json.loads(settings.path.read_text()) == {"embedding_model": "custom-embedding-model"}


def test_invalid_embedding_model_fails_clearly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = memory_settings(tmp_path)

    with pytest.raises(InvalidEmbeddingModelError, match="must be a non-empty string"):
        settings.update(embedding_model="  ")
    monkeypatch.setenv(EMBEDDING_MODEL_ENV, "  ")
    with pytest.raises(InvalidEmbeddingModelError, match="must be a non-empty string"):
        settings.as_dict()


def test_invalid_embedding_file_model_fails_clearly(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)
    settings.path.parent.mkdir(parents=True)
    settings.path.write_text(json.dumps({"embedding_model": "  "}))

    with pytest.raises(InvalidEmbeddingModelError, match="must be a non-empty string"):
        settings.as_dict()


def test_clear_embedding_model_returns_default(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)
    settings.update(embedding_model="custom-embedding-model")

    settings.update(embedding_model=None)

    assert settings.embedding_model == DEFAULT_EMBEDDING_MODEL
    assert settings.as_dict()["embedding_model"] == DEFAULT_EMBEDDING_MODEL
    assert json.loads(settings.path.read_text()) == {}


def test_tool_summary_concurrency_persists_and_env_override_wins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = memory_settings(tmp_path)

    settings.update(tool_summary_concurrency=25)

    assert settings.tool_summary_concurrency == 25
    monkeypatch.setenv(TOOL_SUMMARY_CONCURRENCY_ENV, "40")
    assert settings.tool_summary_concurrency == 40
    assert settings.as_dict()["tool_summary_concurrency"] == 40
    assert json.loads(settings.path.read_text()) == {"tool_summary_concurrency": 25}


def test_invalid_tool_summary_concurrency_fails_clearly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = memory_settings(tmp_path)

    for value in (0, 101, True):
        with pytest.raises(InvalidToolSummaryConcurrencyError, match="integer from 1 to 100"):
            settings.update(tool_summary_concurrency=value)
    monkeypatch.setenv(TOOL_SUMMARY_CONCURRENCY_ENV, "not-an-int")
    with pytest.raises(InvalidToolSummaryConcurrencyError, match="integer from 1 to 100"):
        settings.as_dict()


def test_clear_tool_summary_model_persists_absence(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)
    settings.update(interpretation_model="openai:any-model", tool_summary_model="openai:small-model")

    settings.update(tool_summary_model=None)

    assert settings.as_dict() == {
        "interpretation_model": "openai:any-model",
        "tool_summary_model": None,
        "quality_model": None,
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        "tool_summary_concurrency": DEFAULT_TOOL_SUMMARY_CONCURRENCY,
    }
    assert json.loads(settings.path.read_text()) == {"interpretation_model": "openai:any-model"}


def test_invalid_model_fails_clearly(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)

    with pytest.raises(InvalidInterpretationModelError, match="must be a non-empty string"):
        settings.update(interpretation_model="  ")
    with pytest.raises(InvalidInterpretationModelError, match="must be a non-empty string"):
        settings.update(tool_summary_model="  ")
    with pytest.raises(InvalidInterpretationModelError, match="must be a non-empty string"):
        settings.update(quality_model="  ")


def test_invalid_env_model_fails_clearly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = memory_settings(tmp_path)
    monkeypatch.setenv(INTERPRETATION_MODEL_ENV, "  ")

    with pytest.raises(InvalidInterpretationModelError, match="must be a non-empty string"):
        settings.as_dict()


def test_invalid_quality_env_model_fails_clearly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = memory_settings(tmp_path)
    monkeypatch.setenv(QUALITY_MODEL_ENV, "  ")

    with pytest.raises(InvalidInterpretationModelError, match="must be a non-empty string"):
        settings.as_dict()


def test_invalid_quality_file_model_fails_clearly(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)
    settings.path.parent.mkdir(parents=True)
    settings.path.write_text(json.dumps({"quality_model": "  "}))

    with pytest.raises(InvalidInterpretationModelError, match="must be a non-empty string"):
        settings.as_dict()


def test_clear_model_persists_absence(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)
    settings.update(interpretation_model="openai:any-model")

    settings.update(interpretation_model=None)

    assert settings.as_dict() == {
        "interpretation_model": None,
        "tool_summary_model": None,
        "quality_model": None,
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        "tool_summary_concurrency": DEFAULT_TOOL_SUMMARY_CONCURRENCY,
    }
    assert json.loads(settings.path.read_text()) == {}


def test_clear_quality_model_persists_absence(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)
    settings.update(interpretation_model="openai:any-model", quality_model="openai:quality-model")

    settings.update(quality_model=None)

    assert settings.as_dict() == {
        "interpretation_model": "openai:any-model",
        "tool_summary_model": None,
        "quality_model": None,
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        "tool_summary_concurrency": DEFAULT_TOOL_SUMMARY_CONCURRENCY,
    }
    assert json.loads(settings.path.read_text()) == {"interpretation_model": "openai:any-model"}


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
