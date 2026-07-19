"""Tests for the `basecamp config` command group (generic + porcelain)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import basecamp.core.cli.config_document as config_document
import basecamp.core.cli.config_group as config_group
import basecamp.core.cli.project as cli_project
import basecamp.core.model_aliases as model_aliases
import basecamp.core.projects as projects
import basecamp.workspace.environments as environments
from basecamp.core.cli.config_group import config
from basecamp.core.settings import Settings


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Redirect every module's `settings` singleton at a temp config.json.

    Must cover every module whose code path a `config` subcommand reaches —
    including the project porcelain's writers (projects / cli.project) — so a
    test can never touch the developer's real ~/.pi/basecamp/config.json.
    """
    settings = Settings(tmp_path / "config.json")
    for module in (config_document, config_group, model_aliases, environments, projects, cli_project):
        monkeypatch.setattr(module, "settings", settings)
    return settings


def _doc(cfg: Settings) -> dict:
    return json.loads(cfg.path.read_text())


# --- generic plumbing ---------------------------------------------------------


def test_set_get_unset_roundtrip(cfg: Settings) -> None:
    runner = CliRunner()
    assert runner.invoke(config, ["set", "logseq.graph_dir", "~/logseq"]).exit_code == 0
    assert _doc(cfg)["logseq"] == {"graph_dir": "~/logseq"}

    got = runner.invoke(config, ["get", "logseq.graph_dir"])
    assert got.exit_code == 0 and "~/logseq" in got.output

    assert runner.invoke(config, ["unset", "logseq.graph_dir"]).exit_code == 0
    assert _doc(cfg)["logseq"] == {}


def test_set_validation_failure_exits_nonzero(cfg: Settings) -> None:
    result = CliRunner().invoke(config, ["set", "model_aliases.bad", "   "])
    assert result.exit_code == 1
    assert not cfg.path.exists()


def test_show_succeeds(cfg: Settings) -> None:
    cfg.set_section("projects", {"demo": {"repo_root": "src/demo"}})
    assert CliRunner().invoke(config, ["show"]).exit_code == 0


# --- porcelain: same file, same validator -------------------------------------


def test_alias_porcelain_matches_generic(cfg: Settings) -> None:
    runner = CliRunner()
    assert runner.invoke(config, ["alias", "set", "fast", "claude-haiku-4-5"]).exit_code == 0
    assert _doc(cfg)["model_aliases"] == {"fast": "claude-haiku-4-5"}
    assert runner.invoke(config, ["alias", "set", "bad", "  "]).exit_code == 1


def test_env_porcelain_sets_and_preserves_siblings(cfg: Settings) -> None:
    runner = CliRunner()
    runner.invoke(config, ["set", "model_aliases.fast", "m"])

    assert runner.invoke(config, ["env", "set", "acme/widget", "uv sync"]).exit_code == 0
    doc = _doc(cfg)
    assert doc["environments"] == {"acme/widget": {"setup": "uv sync"}}
    assert doc["model_aliases"] == {"fast": "m"}


def test_alias_rename(cfg: Settings) -> None:
    runner = CliRunner()
    runner.invoke(config, ["alias", "set", "fast", "claude-haiku-4-5"])

    result = runner.invoke(config, ["alias", "rename", "fast", "quick"])

    assert result.exit_code == 0
    assert _doc(cfg).get("model_aliases") == {"quick": "claude-haiku-4-5"}


def test_fixture_redirects_project_writer_modules(cfg: Settings) -> None:
    # The project porcelain writes via these modules; if the fixture didn't
    # redirect them a `config project` test would mutate the real config.
    assert projects.settings.path == cfg.path
    assert cli_project.settings.path == cfg.path  # untouched by the env write
