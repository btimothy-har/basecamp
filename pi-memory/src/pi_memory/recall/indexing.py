"""Derived full-text indexing for raw Pi transcript entries."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from pi_memory.db import TranscriptEntry

_WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class TranscriptIndexResult:
    """Summary of transcript FTS indexing work."""

    total_entries: int
    indexed_entries: int


def extract_search_text(entry: TranscriptEntry) -> str | None:
    """Extract deterministic search text from a stored Pi transcript entry.

    Args:
        entry: Canonical transcript entry containing raw JSON and parsed metadata.

    Returns:
        Whitespace-normalized search text, or None when the entry has no useful
        searchable content.
    """
    try:
        payload = json.loads(entry.raw_line)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    extracted = _extract_payload_text(entry, payload)
    if not extracted:
        return None

    metadata = _entry_metadata(entry, payload)
    return _normalize_text(" ".join([*metadata, *extracted]))


def index_transcript(session: Session, transcript_id: int) -> TranscriptIndexResult:
    """Idempotently index useful transcript entries into the FTS projection.

    Args:
        session: Active SQLAlchemy session participating in the caller's
            transaction.
        transcript_id: Transcript database id to index.

    Returns:
        Count of canonical entries considered and FTS rows inserted.
    """
    entries = list(
        session.scalars(
            select(TranscriptEntry)
            .where(TranscriptEntry.transcript_id == transcript_id)
            .order_by(TranscriptEntry.byte_start, TranscriptEntry.id),
        ),
    )
    session.execute(
        text(
            """
            DELETE FROM transcript_entries_fts
            WHERE rowid IN (
                SELECT id
                FROM transcript_entries
                WHERE transcript_id = :transcript_id
            )
            """,
        ),
        {"transcript_id": transcript_id},
    )

    indexed_entries = 0
    for entry in entries:
        search_text = extract_search_text(entry)
        if search_text is None:
            continue

        session.execute(
            text(
                """
                INSERT INTO transcript_entries_fts(rowid, search_text)
                VALUES (:rowid, :search_text)
                """,
            ),
            {"rowid": entry.id, "search_text": search_text},
        )
        indexed_entries += 1

    return TranscriptIndexResult(total_entries=len(entries), indexed_entries=indexed_entries)


def _extract_payload_text(entry: TranscriptEntry, payload: dict[str, Any]) -> list[str]:
    match entry.entry_type:
        case "message":
            return _message_text(payload)
        case "custom_message":
            return _custom_message_text(payload)
        case "custom":
            return _custom_text(payload)
        case "compaction":
            return _string_field(payload, "summary")
        case "branch_summary":
            return _string_fields(payload, ["summary", "fromId"])
        case "session_info":
            return _string_field(payload, "name")
        case "model_change":
            return _string_fields(payload, ["provider", "modelId"])
        case "thinking_level_change":
            return _string_field(payload, "thinkingLevel")
        case "session":
            return _string_field(payload, "cwd")
        case _:
            return []


def _entry_metadata(entry: TranscriptEntry, payload: dict[str, Any]) -> list[str]:
    metadata = [entry.entry_type]
    if entry.message_role:
        metadata.append(entry.message_role)

    custom_type = payload.get("customType")
    if isinstance(custom_type, str):
        metadata.append(custom_type)

    return metadata


def _message_text(payload: dict[str, Any]) -> list[str]:
    message = payload.get("message")
    if not isinstance(message, dict):
        return []

    return _content_parts_text(message.get("content"))


def _custom_message_text(payload: dict[str, Any]) -> list[str]:
    return _content_parts_text(payload.get("content"))


def _custom_text(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []

    return _leaf_text(data)


def _content_parts_text(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content] if content.strip() else []

    if not isinstance(content, list):
        return []

    extracted: list[str] = []
    for part in content:
        if isinstance(part, str):
            if part.strip():
                extracted.append(part)
            continue
        if not isinstance(part, dict):
            continue

        match part.get("type"):
            case "text":
                extracted.extend(_string_field(part, "text"))
            case "thinking":
                extracted.extend(_string_field(part, "thinking"))
            case "toolCall":
                extracted.extend(_tool_call_text(part))

    return extracted


def _tool_call_text(part: dict[str, Any]) -> list[str]:
    extracted: list[str] = []
    name = part.get("name")
    if isinstance(name, str) and name.strip():
        extracted.append(name)

    arguments = part.get("arguments")
    if _has_useful_leaf(arguments):
        extracted.append(json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")))

    return extracted


def _string_fields(payload: dict[str, Any], keys: list[str]) -> list[str]:
    extracted: list[str] = []
    for key in keys:
        extracted.extend(_string_field(payload, key))
    return extracted


def _string_field(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _leaf_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, int | float):
        return [str(value)]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _leaf_text(item)]
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in _leaf_text(item)]
    return []


def _has_useful_leaf(value: Any) -> bool:
    return bool(_leaf_text(value))


def _normalize_text(value: str) -> str | None:
    normalized = _WHITESPACE_PATTERN.sub(" ", value).strip()
    if not normalized:
        return None
    return normalized
