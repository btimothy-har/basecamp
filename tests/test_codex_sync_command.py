from __future__ import annotations

import pytest
import tomlkit

import basecamp.codex_sync.command as command
from basecamp.codex_sync.agents import AGENTS
from basecamp.codex_sync.assets import OPERATING_GUIDELINES


def test_run_codex_sync_uses_codex_home_and_creates_directories(tmp_path, monkeypatch) -> None:
    codex_home = tmp_path / "codex-home"
    skills_dir = tmp_path / "skills"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    result = command.run_codex_sync(skills_dir=skills_dir)

    assert result.codex_home == codex_home
    assert result.config_path == codex_home / "config.toml"
    assert result.agents_dir == codex_home / "agents"
    assert result.skills_dir == skills_dir
    assert codex_home.is_dir()
    assert (codex_home / "agents").is_dir()
    assert skills_dir.is_dir()
    assert result.config_changed is True
    assert result.agents.installed == 5
    assert result.skills.installed == 3

    config = tomlkit.parse((codex_home / "config.toml").read_text())
    assert config["developer_instructions"] == OPERATING_GUIDELINES
    assert "sandbox_workspace_write" not in config


def test_run_codex_sync_defaults_to_home_dot_codex(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(command.Path, "home", lambda: tmp_path)

    result = command.run_codex_sync()

    assert result.codex_home == tmp_path / ".codex"
    assert result.skills_dir == tmp_path / ".agents" / "skills"
    assert result.config_path.exists()
    assert result.skills_dir.exists()


def test_run_codex_sync_expands_codex_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", "~/custom-codex")

    result = command.run_codex_sync(skills_dir=tmp_path / "skills")

    assert result.codex_home == tmp_path / "custom-codex"
    assert result.config_path.exists()


def test_run_codex_sync_wraps_config_errors(tmp_path) -> None:
    codex_home = tmp_path / "codex-home"
    config_path = codex_home / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("invalid = [")

    with pytest.raises(command.CodexSyncError, match="Invalid TOML"):
        command.run_codex_sync(codex_home=codex_home, skills_dir=tmp_path / "skills")


def test_run_codex_sync_wraps_filesystem_errors(tmp_path) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.write_text("not a directory")

    with pytest.raises(command.CodexSyncError):
        command.run_codex_sync(codex_home=codex_home, skills_dir=tmp_path / "skills")


def test_run_codex_sync_preflights_agent_conflicts_before_config_write(tmp_path) -> None:
    codex_home = tmp_path / "codex-home"
    skills_dir = tmp_path / "skills"
    config_path = codex_home / "config.toml"
    agents_dir = codex_home / "agents"
    config_path.parent.mkdir(parents=True)
    agents_dir.mkdir()
    skills_dir.mkdir()
    original = 'developer_instructions = "Keep this instruction."\n'
    config_path.write_text(original)
    (agents_dir / AGENTS[0].filename).write_text('name = "custom"\n')

    with pytest.raises(command.CodexSyncError, match="Refusing to overwrite"):
        command.run_codex_sync(codex_home=codex_home, skills_dir=skills_dir)

    assert config_path.read_text() == original


def test_run_codex_sync_preflights_skill_conflicts_before_config_write(tmp_path) -> None:
    codex_home = tmp_path / "codex-home"
    skills_dir = tmp_path / "skills"
    config_path = codex_home / "config.toml"
    config_path.parent.mkdir(parents=True)
    skills_dir.mkdir()
    original = 'developer_instructions = "Keep this instruction."\n'
    config_path.write_text(original)
    (skills_dir / "python-development").mkdir()
    (skills_dir / "python-development" / "SKILL.md").write_text("---\nname: custom\ndescription: custom\n---\n")

    with pytest.raises(command.CodexSyncError, match="Refusing to overwrite"):
        command.run_codex_sync(codex_home=codex_home, skills_dir=skills_dir)

    assert config_path.read_text() == original
