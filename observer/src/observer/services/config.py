"""Persistent configuration for observer.

Stores user-configured settings in a JSON file at
~/.basecamp/observer/config.json so they are available across all invocation
paths — CLI commands, MCP server, hooks — without relying on shell
environment variables, which subprocess spawning may not propagate.
"""

from __future__ import annotations

import json
import os

from observer.constants import (
    BASECAMP_DIR,
    DEFAULT_OBSERVER_MODEL,
    OBSERVER_DIR,
)

CONFIG_FILE = OBSERVER_DIR / "config.json"
_CORE_CONFIG = BASECAMP_DIR / "config.json"

_EXTENDED_CONTEXT_MODELS: dict[str, str] = {
    "sonnet": "sonnet[1m]",
    "opus": "opus[1m]",
}


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


def _use_extended_context() -> bool:
    """Check if extended context is enabled in core config."""
    try:
        data = json.loads(_CORE_CONFIG.read_text())
        return bool(data.get("use_extended_context"))
    except (json.JSONDecodeError, OSError):
        return False


def resolve_model(model: str) -> str:
    """Apply extended context suffix when enabled in core settings."""
    if _use_extended_context():
        return _EXTENDED_CONTEXT_MODELS.get(model, model)
    return model


def get_extraction_model() -> str:
    """Return the configured extraction model, falling back to the default."""
    model = _read().get("extraction_model") or DEFAULT_OBSERVER_MODEL
    return resolve_model(model)


def set_extraction_model(model: str) -> None:
    """Persist the extraction model to the config file."""
    data = _read()
    data["extraction_model"] = model
    _write(data)


def get_summary_model() -> str:
    """Return the configured summary model, falling back to the default."""
    model = _read().get("summary_model") or DEFAULT_OBSERVER_MODEL
    return resolve_model(model)


def set_summary_model(model: str) -> None:
    """Persist the summary model to the config file."""
    data = _read()
    data["summary_model"] = model
    _write(data)


def get_mode() -> str:
    """Return the observer processing mode: 'on' or 'off'.

    Handles backward compat with old 'full'/'lite' mode values.
    """
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
    data.pop("extraction_enabled", None)  # clean up old key
    _write(data)
