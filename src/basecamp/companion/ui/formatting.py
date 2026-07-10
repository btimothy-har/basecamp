"""Shared formatting helpers for the companion TUI."""

from __future__ import annotations

from datetime import datetime

_STATUS_GLYPH = {"completed": "✓", "active": "▶", "pending": "○", "deleted": "✕"}


def _truncate_preview(text: str, *, max_length: int) -> str:
    cleaned = text.replace("\n", " ").strip()
    if len(cleaned) <= max_length:
        return cleaned

    suffix = "…"
    available = max_length - len(suffix)
    if available <= 0:
        return suffix

    return f"{cleaned[:available].rstrip()}{suffix}" if cleaned[:available].strip() else suffix


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None

    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"

    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _format_activity_timestamp(value: str | None) -> str | None:
    timestamp = _parse_iso_timestamp(value)
    if timestamp is not None:
        return timestamp.strftime("%H:%M:%S")

    if not value:
        return None

    cleaned = value.strip()
    if "T" in cleaned:
        time_part = cleaned.split("T", maxsplit=1)[1]
        time_part = time_part.removesuffix("Z").split("+", maxsplit=1)[0]
        if len(time_part) >= 8:
            return time_part[:8]

    return _truncate_preview(cleaned, max_length=12)


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"

    if seconds < 3600:
        mins, secs = divmod(seconds, 60)
        return f"{mins}m{'' if secs == 0 else f' {secs}s'}"

    if seconds < 86400:
        hours, remainder = divmod(seconds, 3600)
        mins, _ = divmod(remainder, 60)
        return f"{hours}h {mins}m"

    days, remainder = divmod(seconds, 86400)
    hours, _ = divmod(remainder, 3600)
    return f"{days}d {hours}h"
