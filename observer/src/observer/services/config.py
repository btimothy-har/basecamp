"""Persistent configuration for observer.

Stores user-configured settings in a JSON file at
~/.basecamp/observer/config.json so they are available across all invocation
paths — daemon, MCP server, session-register hook — without relying on shell
environment variables, which subprocess spawning may not propagate.
"""

from __future__ import annotations

import json
import os

from observer.constants import (
    DEFAULT_EXTRACTION_MODEL,
    DEFAULT_SUMMARY_MODEL,
    OBSERVER_DIR,
)

CONFIG_FILE = OBSERVER_DIR / "config.json"


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
    # O_CREAT | O_TRUNC with mode 0o600 sets permissions atomically — no TOCTOU window.
    fd = os.open(str(CONFIG_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, content)
    finally:
        os.close(fd)


def get_pg_url() -> str | None:
    """Return the stored PostgreSQL URL, or None if not configured."""
    return _read().get("pg_url") or None


def set_pg_url(url: str) -> None:
    """Persist the PostgreSQL URL to the config file."""
    data = _read()
    data["pg_url"] = url
    _write(data)


def get_db_source() -> str | None:
    """Return the stored database source ("container" or "user"), or None."""
    return _read().get("db_source") or None


def set_db_source(source: str) -> None:
    """Persist the database source to the config file."""
    data = _read()
    data["db_source"] = source
    _write(data)


def get_extraction_model() -> str:
    """Return the configured extraction model, falling back to the default."""
    return _read().get("extraction_model") or DEFAULT_EXTRACTION_MODEL


def set_extraction_model(model: str) -> None:
    """Persist the extraction model to the config file."""
    data = _read()
    data["extraction_model"] = model
    _write(data)


def get_summary_model() -> str:
    """Return the configured summary model, falling back to the default."""
    return _read().get("summary_model") or DEFAULT_SUMMARY_MODEL


def set_summary_model(model: str) -> None:
    """Persist the summary model to the config file."""
    data = _read()
    data["summary_model"] = model
    _write(data)


def get_mode() -> str:
    """Return the observer processing mode: 'full', 'lite', or 'off'.

    Handles backward compat with the old extraction_enabled boolean.
    """
    data = _read()
    mode = data.get("mode")
    if mode in ("full", "lite", "off"):
        return mode
    # Backward compat: old configs used extraction_enabled boolean
    if "extraction_enabled" in data:
        return "full" if data["extraction_enabled"] else "off"
    return "full"


def set_mode(mode: str) -> None:
    """Persist the processing mode to the config file."""
    if mode not in ("full", "lite", "off"):
        msg = f"Invalid mode: {mode!r}. Must be 'full', 'lite', or 'off'."
        raise ValueError(msg)
    data = _read()
    data["mode"] = mode
    data.pop("extraction_enabled", None)  # clean up old key
    _write(data)
