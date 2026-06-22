from __future__ import annotations

import pytest
import tomlkit

import basecamp.codex_sync.command as command
from basecamp.codex_sync.assets import WORKING_PREFERENCES


def test_run_codex_sync_uses_codex_home_and_creates_directories(tmp_path, monkeypatch) -> None:
    codex_home = tmp_path / "codex-home"
    scratch = tmp_path / "scratch"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    result = command.run_codex_sync(scratch_dir=scratch)

    assert result.codex_home == codex_home
    assert result.config_path == codex_home / "config.toml"
    assert result.agents_dir == codex_home / "agents"
    assert result.scratch_dir == scratch
    assert codex_home.is_dir()
    assert (codex_home / "agents").is_dir()
    assert scratch.is_dir()
    assert result.config_changed is True
    assert result.agents.installed == 5

    config = tomlkit.parse((codex_home / "config.toml").read_text())
    assert config["developer_instructions"] == WORKING_PREFERENCES
    assert config["sandbox_workspace_write"]["writable_roots"] == [str(scratch)]


def test_run_codex_sync_defaults_to_home_dot_codex(tmp_path, monkeypatch) -> None:
    scratch = tmp_path / "scratch"
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(command.Path, "home", lambda: tmp_path)

    result = command.run_codex_sync(scratch_dir=scratch)

    assert result.codex_home == tmp_path / ".codex"
    assert result.config_path.exists()
    assert scratch.is_dir()


def test_run_codex_sync_expands_codex_home(tmp_path, monkeypatch) -> None:
    scratch = tmp_path / "scratch"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", "~/custom-codex")

    result = command.run_codex_sync(scratch_dir=scratch)

    assert result.codex_home == tmp_path / "custom-codex"
    assert result.config_path.exists()


def test_run_codex_sync_wraps_config_errors(tmp_path) -> None:
    codex_home = tmp_path / "codex-home"
    config_path = codex_home / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("invalid = [")

    with pytest.raises(command.CodexSyncError, match="Invalid TOML"):
        command.run_codex_sync(codex_home=codex_home, scratch_dir=tmp_path / "scratch")
