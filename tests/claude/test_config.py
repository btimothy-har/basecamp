"""Tests for basecamp.claude.config — the own flock'd .claude/basecamp.json reader."""

from __future__ import annotations

import json
from pathlib import Path

from basecamp.claude.config import ClaudeConfig
from basecamp.claude.paths import config_path


def test_config_path_points_under_dot_claude(tmp_path: Path) -> None:
    assert config_path(tmp_path) == tmp_path / ".claude" / "basecamp.json"


def test_read_missing_is_empty(tmp_path: Path) -> None:
    cfg = ClaudeConfig(home=tmp_path)
    assert cfg.read() == {}
    assert cfg.get_section("logseq") == {}


def test_read_corrupt_is_empty(tmp_path: Path) -> None:
    path = config_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert ClaudeConfig(home=tmp_path).read() == {}


def test_get_section_returns_dict(tmp_path: Path) -> None:
    path = config_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"logseq": {"graph_dir": "~/g"}, "scalar": 3}))
    cfg = ClaudeConfig(home=tmp_path)
    assert cfg.get_section("logseq") == {"graph_dir": "~/g"}
    # non-dict section coerces to {}
    assert cfg.get_section("scalar") == {}


def test_set_section_roundtrip_locked_write(tmp_path: Path) -> None:
    cfg = ClaudeConfig(home=tmp_path)
    cfg.set_section("logseq", {"graph_dir": str(tmp_path / "graph")})
    # a fresh reader sees the persisted value
    assert ClaudeConfig(home=tmp_path).get_section("logseq") == {"graph_dir": str(tmp_path / "graph")}
    # written atomically with a sibling lock file, under .claude
    assert config_path(tmp_path).exists()


def test_explicit_path_overrides_home(tmp_path: Path) -> None:
    custom = tmp_path / "custom.json"
    custom.write_text(json.dumps({"logseq": {"graph_dir": "/x"}}))
    assert ClaudeConfig(path=custom).get_section("logseq") == {"graph_dir": "/x"}
