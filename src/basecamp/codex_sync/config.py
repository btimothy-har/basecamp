"""Codex config merge support."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import TOMLKitError

from basecamp.codex_sync.assets import WORKING_PREFERENCES

_WORKING_PREFERENCES_RE = re.compile(r"<working_preferences>.*?</working_preferences>", re.DOTALL)


class CodexConfigError(Exception):
    """Raised when Codex config cannot be safely merged."""


class InvalidCodexConfigError(CodexConfigError):
    """Raised when config TOML is invalid."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Invalid TOML in {path}; leaving file unchanged.")


class UnsupportedDeveloperInstructionsError(CodexConfigError):
    """Raised when developer_instructions has an unsupported value."""

    def __init__(self) -> None:
        super().__init__("Unsupported developer_instructions value; expected a string.")


def merge_config(config_path: Path) -> bool:
    """Merge Codex user config, preserving existing TOML comments.

    Returns:
        True when the file content changed, False when already current.
    """
    previous = config_path.read_text() if config_path.exists() else ""
    document = _parse_config(previous, config_path)

    _merge_developer_instructions(document)

    rendered = tomlkit.dumps(document)
    if rendered == previous:
        return False

    config_path.write_text(rendered)
    return True


def _parse_config(content: str, config_path: Path) -> Any:
    if not content:
        return tomlkit.document()

    try:
        return tomlkit.parse(content)
    except TOMLKitError as error:
        raise InvalidCodexConfigError(config_path) from error


def _merge_developer_instructions(document: Any) -> None:
    existing = document.get("developer_instructions")
    if existing is None or (isinstance(existing, str) and not existing.strip()):
        document["developer_instructions"] = WORKING_PREFERENCES
        return

    if not isinstance(existing, str):
        raise UnsupportedDeveloperInstructionsError()

    if _WORKING_PREFERENCES_RE.search(existing):
        document["developer_instructions"] = _WORKING_PREFERENCES_RE.sub(WORKING_PREFERENCES, existing)
        return

    document["developer_instructions"] = f"{existing}\n\n{WORKING_PREFERENCES}"
