"""Tests for generic dotted-path config access (config get/set/unset/edit)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from basecamp.core.cli import config_document as cd
from basecamp.core.exceptions import LauncherError
from basecamp.core.settings import Settings


@pytest.fixture
def cfg(tmp_path: Path) -> Settings:
    return Settings(tmp_path / "config.json")


def _doc(cfg: Settings) -> dict:
    return json.loads(cfg.path.read_text())


def test_set_across_sections_and_normalizes(cfg: Settings) -> None:
    cd.set_value("model_aliases.fast", "  claude-haiku-4-5  ", config=cfg)  # normalized by validator
    cd.set_value("logseq.graph_dir", "~/logseq", config=cfg)  # writer-less section
    cd.set_value("projects.demo.repo_root", "src/demo", config=cfg)  # rich record

    doc = _doc(cfg)
    assert doc["model_aliases"] == {"fast": "claude-haiku-4-5"}
    assert doc["logseq"] == {"graph_dir": "~/logseq"}
    assert doc["projects"]["demo"]["repo_root"] == "src/demo"  # pydantic-normalized
    assert doc["projects"]["demo"]["additional_dirs"] == []


def test_get_reads_and_raises_on_missing(cfg: Settings) -> None:
    cd.set_value("model_aliases.fast", "m", config=cfg)
    assert cd.get_value("model_aliases.fast", config=cfg) == "m"
    with pytest.raises(LauncherError):
        cd.get_value("model_aliases.missing", config=cfg)


@pytest.mark.parametrize("raw", ["", "   "])
def test_set_rejects_invalid_section_value(cfg: Settings, raw: str) -> None:
    with pytest.raises(LauncherError):
        cd.set_value("model_aliases.bad", raw, config=cfg)


def test_set_json_flag_parses_structured_values(cfg: Settings) -> None:
    cd.set_value("projects.demo.repo_root", "src/demo", config=cfg)
    cd.set_value("projects.demo.additional_dirs", '["a", "b"]', as_json=True, config=cfg)
    assert _doc(cfg)["projects"]["demo"]["additional_dirs"] == ["a", "b"]


def test_set_guards_against_clobbering_a_scalar(cfg: Settings) -> None:
    cd.set_value("logseq.graph_dir", "~/logseq", config=cfg)
    with pytest.raises(LauncherError):
        cd.set_value("logseq.graph_dir.deep", "x", config=cfg)


def test_unset_removes_and_preserves_siblings(cfg: Settings) -> None:
    cd.set_value("model_aliases.fast", "m", config=cfg)
    cd.set_value("logseq.graph_dir", "~/logseq", config=cfg)

    assert cd.unset_value("model_aliases.fast", config=cfg) is True
    assert cd.unset_value("model_aliases.fast", config=cfg) is False  # already gone
    doc = _doc(cfg)
    assert doc["model_aliases"] == {}
    assert doc["logseq"] == {"graph_dir": "~/logseq"}


def test_unset_rejected_when_it_breaks_a_record(cfg: Settings) -> None:
    cd.set_value("projects.demo.repo_root", "src/demo", config=cfg)
    with pytest.raises(LauncherError):
        cd.unset_value("projects.demo.repo_root", config=cfg)  # repo_root is required
    assert _doc(cfg)["projects"]["demo"]["repo_root"] == "src/demo"


def test_edit_persists_valid_and_rejects_invalid(cfg: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    cd.set_value("model_aliases.fast", "m", config=cfg)

    # No change → False.
    monkeypatch.setattr(cd.click, "edit", lambda *_a, **_k: None)
    assert cd.edit_document(config=cfg) is False

    # Valid replacement → persists, validated/normalized.
    monkeypatch.setattr(cd.click, "edit", lambda *_a, **_k: '{"model_aliases": {" x ": " y "}}')
    assert cd.edit_document(config=cfg) is True
    assert _doc(cfg)["model_aliases"] == {"x": "y"}

    # Invalid JSON → raises, file unchanged.
    monkeypatch.setattr(cd.click, "edit", lambda *_a, **_k: "{ not json")
    with pytest.raises(LauncherError):
        cd.edit_document(config=cfg)
    assert _doc(cfg)["model_aliases"] == {"x": "y"}

    # Structurally invalid section → raises, file unchanged.
    monkeypatch.setattr(cd.click, "edit", lambda *_a, **_k: '{"projects": {"demo": {"nope": 1}}}')
    with pytest.raises(LauncherError):
        cd.edit_document(config=cfg)
    assert _doc(cfg)["model_aliases"] == {"x": "y"}
