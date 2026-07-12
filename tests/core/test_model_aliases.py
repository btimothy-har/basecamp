"""Tests for the model_aliases section of the unified config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from basecamp.core.exceptions import LauncherError
from basecamp.core.model_aliases import load_model_aliases, remove_alias, set_alias
from basecamp.core.settings import CONFIG_VERSION, Settings


@pytest.fixture
def cfg(tmp_path: Path) -> Settings:
    return Settings(tmp_path / "config.json")


def test_set_alias_trims_and_persists(cfg: Settings) -> None:
    stored = set_alias("  fast  ", "  claude-haiku-4-5  ", cfg)

    assert stored == ("fast", "claude-haiku-4-5")
    data = json.loads(cfg.path.read_text())
    assert data["version"] == CONFIG_VERSION
    assert data["model_aliases"] == {"fast": "claude-haiku-4-5"}
    assert load_model_aliases(cfg) == {"fast": "claude-haiku-4-5"}


def test_set_alias_overwrites(cfg: Settings) -> None:
    set_alias("fast", "model-a", cfg)
    set_alias("fast", "model-b", cfg)

    assert load_model_aliases(cfg) == {"fast": "model-b"}


@pytest.mark.parametrize("alias,model", [("  ", "model"), ("fast", "   ")])
def test_set_alias_rejects_empty(cfg: Settings, alias: str, model: str) -> None:
    with pytest.raises(LauncherError):
        set_alias(alias, model, cfg)
    assert not cfg.path.exists()


def test_remove_alias_reports_whether_present(cfg: Settings) -> None:
    set_alias("fast", "model-a", cfg)
    set_alias("slow", "model-b", cfg)

    assert remove_alias(" fast ", cfg) is True
    assert remove_alias("missing", cfg) is False
    assert load_model_aliases(cfg) == {"slow": "model-b"}


def test_writes_preserve_other_sections(cfg: Settings) -> None:
    cfg._write({"projects": {"demo": {"repo_root": "src/demo"}}})

    set_alias("fast", "claude-haiku-4-5", cfg)
    remove_alias("fast", cfg)

    data = json.loads(cfg.path.read_text())
    assert data["projects"] == {"demo": {"repo_root": "src/demo"}}


def test_load_skips_non_string_entries(cfg: Settings) -> None:
    cfg.set_section("model_aliases", {"fast": "ok", "bad": 42, "": "empty-key"})

    assert load_model_aliases(cfg) == {"fast": "ok", "": "empty-key"}
