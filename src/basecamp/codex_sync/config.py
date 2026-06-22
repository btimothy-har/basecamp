"""Codex config merge support."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import TOMLKitError
from tomlkit.items import AbstractTable, Array

from basecamp.codex_sync.assets import SCRATCH_ROOT, WORKING_PREFERENCES

WRITABLE_ROOT = SCRATCH_ROOT
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


class UnsupportedSandboxConfigError(CodexConfigError):
    """Raised when sandbox_workspace_write cannot be safely merged."""

    detail = "unsupported shape"

    def __init__(self) -> None:
        super().__init__(f"Unsupported sandbox_workspace_write config: {self.detail}.")


class UnsupportedSandboxTableError(UnsupportedSandboxConfigError):
    """Raised when sandbox_workspace_write is not a table."""

    detail = "expected a table"


class UnsupportedWritableRootsArrayError(UnsupportedSandboxConfigError):
    """Raised when writable_roots is not an array."""

    detail = "writable_roots must be an array of strings"


class UnsupportedWritableRootsEntriesError(UnsupportedSandboxConfigError):
    """Raised when writable_roots contains non-string entries."""

    detail = "writable_roots must contain only strings"


def merge_config(config_path: Path, *, writable_root: str = WRITABLE_ROOT) -> bool:
    """Merge Codex user config, preserving existing TOML comments.

    Returns:
        True when the file content changed, False when already current.
    """
    previous = config_path.read_text() if config_path.exists() else ""
    document = _parse_config(previous, config_path)

    _merge_developer_instructions(document)
    _merge_writable_roots(document, writable_root=writable_root)

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


def _merge_writable_roots(document: Any, *, writable_root: str) -> None:
    sandbox = document.get("sandbox_workspace_write")
    if sandbox is None:
        sandbox = tomlkit.table()
        document["sandbox_workspace_write"] = sandbox
    elif not isinstance(sandbox, AbstractTable):
        raise UnsupportedSandboxTableError()

    roots = sandbox.get("writable_roots")
    if roots is None:
        roots = tomlkit.array()
        sandbox["writable_roots"] = roots
    elif not isinstance(roots, (list, Array)):
        raise UnsupportedWritableRootsArrayError()

    if any(not isinstance(root, str) for root in roots):
        raise UnsupportedWritableRootsEntriesError()

    if writable_root not in roots:
        roots.append(writable_root)
