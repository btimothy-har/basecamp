"""Standalone Pi JSONL transcript parser."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ParsedPiEntry:
    """A complete parsed Pi transcript line aligned to transcript entry storage."""

    raw_line: str
    entry_id: str | None
    parent_id: str | None
    entry_type: str
    message_role: str | None
    timestamp: datetime | None
    byte_start: int
    byte_end: int


@dataclass(frozen=True)
class ParseResult:
    """Result of parsing complete Pi transcript lines from a byte offset."""

    entries: list[ParsedPiEntry]
    cursor_offset: int
    file_size: int
    malformed_lines: int = 0
    unsupported_lines: int = 0


class PiTranscriptParser:
    """Parse Pi transcript JSONL files without database coupling."""

    def parse(self, path: Path, offset: int = 0) -> ParseResult:
        """Parse complete newline-terminated Pi JSONL entries from a byte offset.

        Args:
            path: Transcript JSONL file to parse.
            offset: Byte offset where parsing should start.

        Returns:
            Parse result containing parsed entries, next cursor, file size, and skip counts.
        """
        file_size = path.stat().st_size
        cursor_offset = max(offset, 0)
        entries: list[ParsedPiEntry] = []
        malformed_lines = 0
        unsupported_lines = 0

        with path.open("rb") as transcript:
            transcript.seek(cursor_offset)
            while line := transcript.readline():
                byte_start = cursor_offset
                byte_end = byte_start + len(line)

                if not line.endswith(b"\n"):
                    break

                cursor_offset = byte_end
                decoded_line = _decode_line(line)
                if decoded_line is None:
                    malformed_lines += 1
                    continue

                payload = _load_payload(decoded_line)
                if payload is None:
                    malformed_lines += 1
                    continue

                entry = _parse_entry(payload, decoded_line, byte_start, byte_end)
                if entry is None:
                    unsupported_lines += 1
                    continue

                entries.append(entry)

        return ParseResult(
            entries=entries,
            cursor_offset=cursor_offset,
            file_size=file_size,
            malformed_lines=malformed_lines,
            unsupported_lines=unsupported_lines,
        )


def _decode_line(line: bytes) -> str | None:
    try:
        return line.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _load_payload(line: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    return payload


def _parse_entry(
    payload: dict[str, Any],
    raw_line: str,
    byte_start: int,
    byte_end: int,
) -> ParsedPiEntry | None:
    entry_type = payload.get("type")
    if not isinstance(entry_type, str):
        return None

    return ParsedPiEntry(
        raw_line=raw_line,
        entry_id=_optional_string(payload.get("id")),
        parent_id=_optional_string(payload.get("parentId")),
        entry_type=entry_type,
        message_role=_message_role(payload),
        timestamp=_timestamp(payload.get("timestamp")),
        byte_start=byte_start,
        byte_end=byte_end,
    )


def _optional_string(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _message_role(payload: dict[str, Any]) -> str | None:
    message = payload.get("message")
    if not isinstance(message, dict):
        return None

    return _optional_string(message.get("role"))


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)

    return parsed.astimezone(UTC)
