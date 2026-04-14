"""Persistent configuration for observer.

Stores user-configured settings in a JSON file at
~/.basecamp/observer/config.json so they are available across all invocation
paths — CLI commands, hooks — without relying on shell environment variables.

Model identifiers use pydantic-ai's ``provider:model`` format, e.g.:
- ``anthropic:claude-3-5-haiku-latest``
- ``openai:gpt-4o-mini``
- ``anthropic:claude-sonnet-4-20250514``

Legacy short names (``haiku``, ``sonnet``, ``opus``) are migrated
automatically on read.
"""

from __future__ import annotations

import json
import os

from observer.constants import OBSERVER_DIR

CONFIG_FILE = OBSERVER_DIR / "config.json"

# Default models — used when no config exists
DEFAULT_SUMMARY_MODEL = "anthropic:claude-3-5-haiku-latest"
DEFAULT_EXTRACTION_MODEL = "anthropic:claude-sonnet-4-20250514"


def _read() -> dict[str, str]:
    if not CONFIG_FILE.exists():
        return {}
    try:
        parsed = json.loads(CONFIG_FILE.read_text())
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write(data: dict[str, str]) -> None:
    OBSERVER_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)
    content = (json.dumps(data, indent=2) + os.linesep).encode()
    fd = os.open(str(CONFIG_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, content)
    finally:
        os.close(fd)


def get_extraction_model() -> str:
    """Return the configured extraction model as a pydantic-ai model string."""
    return _read().get("extraction_model") or DEFAULT_EXTRACTION_MODEL


def set_extraction_model(model: str) -> None:
    """Persist the extraction model to the config file."""
    data = _read()
    data["extraction_model"] = model
    _write(data)


def get_summary_model() -> str:
    """Return the configured summary model as a pydantic-ai model string."""
    return _read().get("summary_model") or DEFAULT_SUMMARY_MODEL


def set_summary_model(model: str) -> None:
    """Persist the summary model to the config file."""
    data = _read()
    data["summary_model"] = model
    _write(data)


def get_mode() -> str:
    """Return the observer processing mode: 'on' or 'off'."""
    data = _read()
    mode = data.get("mode")
    if mode == "off":
        return "off"
    if mode in ("on", "full", "lite"):
        return "on"
    # Backward compat: old configs used extraction_enabled boolean
    if "extraction_enabled" in data:
        return "on" if data["extraction_enabled"] else "off"
    return "on"


def set_mode(mode: str) -> None:
    """Persist the processing mode to the config file."""
    if mode not in ("on", "off"):
        msg = f"Invalid mode: {mode!r}. Must be 'on' or 'off'."
        raise ValueError(msg)
    data = _read()
    data["mode"] = mode
    data.pop("extraction_enabled", None)
    _write(data)


def get_pg_url() -> str | None:
    """Return the stored PostgreSQL URL, or None if not configured.

    Kept for the pg-migrate command.
    """
    return _read().get("pg_url") or None
