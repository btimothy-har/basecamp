"""Shared module-level helpers: default paths, text sanitization, status semantics."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .messages import MESSAGE_TERMINAL_DELIVERY_STATUSES


def default_db_path() -> Path:
    """Return the default Basecamp swarm daemon database path."""

    return Path.home() / ".pi" / "basecamp" / "swarm" / "daemon.db"


def default_tasks_dir() -> Path:
    """Return the default Basecamp task-log directory."""

    return Path.home() / ".pi" / "basecamp" / "tasks"


RUN_SUMMARY_PREVIEW_CHARS = 160
RUN_SUMMARY_DISPLAY_CHARS = 240
_AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_ANSI_PATTERN = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _fallback_agent_handle(agent_id: str) -> str:
    return agent_id


def _safe_product_role(value: str | None) -> str | None:
    return _display_text(value, limit=64)


def _display_text(value: Any, *, limit: int = RUN_SUMMARY_DISPLAY_CHARS) -> str | None:
    if not isinstance(value, str):
        return None

    text = _ANSI_PATTERN.sub("", value)
    text = _CONTROL_PATTERN.sub("", text)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _preview_text(value: str | None, *, limit: int = RUN_SUMMARY_PREVIEW_CHARS) -> str | None:
    return _display_text(value, limit=limit)


def _message_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    text = _ANSI_PATTERN.sub("", value)
    text = _CONTROL_PATTERN.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return text or None


def _is_valid_agent_id(agent_id: str) -> bool:
    return bool(_AGENT_ID_PATTERN.fullmatch(agent_id))


def _agent_id_short(agent_id: Any) -> str | None:
    if not isinstance(agent_id, str):
        return None
    normalized = re.sub(r"[^A-Za-z0-9]", "", agent_id)
    if not normalized:
        return None
    return normalized[-8:]


def is_message_delivery_terminal(status: str) -> bool:
    """Return whether a public message status is terminal for wait semantics."""

    return status in MESSAGE_TERMINAL_DELIVERY_STATUSES
