from __future__ import annotations

import pytest
import tomlkit

from basecamp.codex_sync.assets import OPERATING_GUIDELINES
from basecamp.codex_sync.config import (
    InvalidCodexConfigError,
    UnsupportedDeveloperInstructionsError,
    merge_config,
)


def test_config_creation_adds_instructions_only(tmp_path) -> None:
    config_path = tmp_path / "config.toml"

    changed = merge_config(config_path)

    assert changed is True
    config = tomlkit.parse(config_path.read_text())
    assert config["developer_instructions"] == OPERATING_GUIDELINES
    assert "sandbox_workspace_write" not in config


def test_existing_instruction_is_preserved_and_operating_guidelines_appended(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('developer_instructions = "Keep this instruction."\n')

    merge_config(config_path)

    config = tomlkit.parse(config_path.read_text())
    assert config["developer_instructions"] == f"Keep this instruction.\n\n{OPERATING_GUIDELINES}"


def test_existing_managed_block_is_replaced_idempotently(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    old_block = "<operating_guidelines>\nold\n</operating_guidelines>"
    config_path.write_text(f'developer_instructions = """Intro\n\n{old_block}\n\nOutro"""\n')

    assert merge_config(config_path) is True
    first = config_path.read_text()
    config = tomlkit.parse(first)
    assert config["developer_instructions"] == f"Intro\n\n{OPERATING_GUIDELINES}\n\nOutro"

    assert merge_config(config_path) is False
    assert config_path.read_text() == first


def test_legacy_working_preferences_block_is_migrated(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    old_block = "<working_preferences>\nold\n</working_preferences>"
    config_path.write_text(f'developer_instructions = """Intro\n\n{old_block}\n\nOutro"""\n')

    merge_config(config_path)

    config = tomlkit.parse(config_path.read_text())
    assert config["developer_instructions"] == f"Intro\n\n{OPERATING_GUIDELINES}\n\nOutro"


def test_operating_guidelines_are_brand_neutral() -> None:
    assert OPERATING_GUIDELINES.startswith("<operating_guidelines>")
    assert OPERATING_GUIDELINES.rstrip().endswith("</operating_guidelines>")
    assert "Basecamp" not in OPERATING_GUIDELINES
    assert "Pi" not in OPERATING_GUIDELINES


def test_existing_sandbox_config_is_preserved_without_writable_roots(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('developer_instructions = ""\n[sandbox_workspace_write]\nnetwork_access = false\n')

    merge_config(config_path)

    config = tomlkit.parse(config_path.read_text())
    assert config["sandbox_workspace_write"]["network_access"] is False
    assert "writable_roots" not in config["sandbox_workspace_write"]


def test_unsupported_sandbox_shape_is_ignored(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('developer_instructions = ""\nsandbox_workspace_write = "custom"\n')

    merge_config(config_path)

    config = tomlkit.parse(config_path.read_text())
    assert config["sandbox_workspace_write"] == "custom"


def test_invalid_toml_fails_without_overwrite(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    original = "not toml = ["
    config_path.write_text(original)

    with pytest.raises(InvalidCodexConfigError):
        merge_config(config_path)

    assert config_path.read_text() == original


def test_unsupported_developer_instructions_type_fails_without_overwrite(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    original = "developer_instructions = 123\n"
    config_path.write_text(original)

    with pytest.raises(UnsupportedDeveloperInstructionsError):
        merge_config(config_path)

    assert config_path.read_text() == original
