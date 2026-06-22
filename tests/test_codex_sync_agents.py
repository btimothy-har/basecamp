from __future__ import annotations

import pytest
import tomlkit

from basecamp.codex_sync.agents import MANAGED_MARKER, UnmanagedAgentConflictError, install_agents
from basecamp.codex_sync.assets import AGENTS


def test_agents_are_written_as_brand_neutral_minimal_toml(tmp_path) -> None:
    result = install_agents(tmp_path)

    assert result.installed == 5
    assert result.updated == 0
    assert result.unchanged == 0

    for agent in AGENTS:
        path = tmp_path / agent.filename
        assert path.exists()
        text = path.read_text()
        assert MANAGED_MARKER in text
        parsed = tomlkit.parse(text)
        assert parsed["name"] == agent.name
        assert parsed["description"] == agent.description
        assert parsed["developer_instructions"] == agent.developer_instructions
        assert "Basecamp" not in parsed["developer_instructions"]
        assert "Pi" not in parsed["developer_instructions"]


def test_managed_agents_are_idempotent(tmp_path) -> None:
    install_agents(tmp_path)

    result = install_agents(tmp_path)

    assert result.installed == 0
    assert result.updated == 0
    assert result.unchanged == 5


def test_managed_agent_is_updated(tmp_path) -> None:
    install_agents(tmp_path)
    path = tmp_path / AGENTS[0].filename
    path.write_text(f'{MANAGED_MARKER}\nname = "old"\n')

    result = install_agents(tmp_path)

    assert result.installed == 0
    assert result.updated == 1
    assert result.unchanged == 4
    assert tomlkit.parse(path.read_text())["name"] == AGENTS[0].name


def test_unmanaged_agent_conflict_fails_without_overwrite(tmp_path) -> None:
    path = tmp_path / AGENTS[0].filename
    original = 'name = "custom"\n'
    path.write_text(original)

    with pytest.raises(UnmanagedAgentConflictError):
        install_agents(tmp_path)

    assert path.read_text() == original
