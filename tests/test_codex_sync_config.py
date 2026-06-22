from __future__ import annotations

import pytest
import tomlkit

from basecamp.codex_sync.assets import WORKING_PREFERENCES
from basecamp.codex_sync.config import (
    WRITABLE_ROOT,
    InvalidCodexConfigError,
    UnsupportedDeveloperInstructionsError,
    UnsupportedSandboxConfigError,
    merge_config,
)


def test_config_creation_adds_instructions_and_writable_root(tmp_path) -> None:
    config_path = tmp_path / "config.toml"

    changed = merge_config(config_path)

    assert changed is True
    config = tomlkit.parse(config_path.read_text())
    assert config["developer_instructions"] == WORKING_PREFERENCES
    assert config["sandbox_workspace_write"]["writable_roots"] == [WRITABLE_ROOT]


def test_existing_instruction_is_preserved_and_working_preferences_appended(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('developer_instructions = "Keep this instruction."\n')

    merge_config(config_path)

    config = tomlkit.parse(config_path.read_text())
    assert config["developer_instructions"] == f"Keep this instruction.\n\n{WORKING_PREFERENCES}"


def test_existing_managed_block_is_replaced_idempotently(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    old_block = "<working_preferences>\nold\n</working_preferences>"
    config_path.write_text(f'developer_instructions = """Intro\n\n{old_block}\n\nOutro"""\n')

    assert merge_config(config_path) is True
    first = config_path.read_text()
    config = tomlkit.parse(first)
    assert config["developer_instructions"] == f"Intro\n\n{WORKING_PREFERENCES}\n\nOutro"

    assert merge_config(config_path) is False
    assert config_path.read_text() == first


def test_writable_root_is_added_to_existing_sandbox_table(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('developer_instructions = ""\n[sandbox_workspace_write]\nnetwork_access = false\n')

    merge_config(config_path)

    config = tomlkit.parse(config_path.read_text())
    assert config["sandbox_workspace_write"]["network_access"] is False
    assert config["sandbox_workspace_write"]["writable_roots"] == [WRITABLE_ROOT]


def test_writable_root_is_added_to_empty_roots_array(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('developer_instructions = ""\n[sandbox_workspace_write]\nwritable_roots = []\n')

    merge_config(config_path)

    config = tomlkit.parse(config_path.read_text())
    assert config["sandbox_workspace_write"]["writable_roots"] == [WRITABLE_ROOT]


def test_writable_root_is_merged_without_duplicates(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'developer_instructions = ""\n[sandbox_workspace_write]\nwritable_roots = ["/existing", "/tmp/codex"]\n'
    )

    merge_config(config_path)

    config = tomlkit.parse(config_path.read_text())
    assert config["sandbox_workspace_write"]["writable_roots"] == ["/existing", WRITABLE_ROOT]


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


@pytest.mark.parametrize(
    "content",
    [
        'sandbox_workspace_write = "bad"\n',
        '[sandbox_workspace_write]\nwritable_roots = "bad"\n',
        "[sandbox_workspace_write]\nwritable_roots = [1]\n",
    ],
)
def test_unsupported_writable_root_shapes_fail_without_overwrite(tmp_path, content) -> None:
    config_path = tmp_path / "config.toml"
    original = f'developer_instructions = ""\n{content}'
    config_path.write_text(original)

    with pytest.raises(UnsupportedSandboxConfigError):
        merge_config(config_path)

    assert config_path.read_text() == original
