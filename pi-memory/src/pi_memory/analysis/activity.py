"""Deterministic Phase 5A transcript activity normalization."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from pi_memory.constants import (
    ACTIVITY_KIND_ASSISTANT_TEXT,
    ACTIVITY_KIND_ASSISTANT_THINKING,
    ACTIVITY_KIND_COMPACTION,
    ACTIVITY_KIND_CUSTOM_EVENT,
    ACTIVITY_KIND_ORPHAN_TOOL_RESULT,
    ACTIVITY_KIND_PENDING_TOOL_CALL,
    ACTIVITY_KIND_SESSION_EVENT,
    ACTIVITY_KIND_TOOL_PAIR,
    ACTIVITY_KIND_USER_TEXT,
    SOURCE_ORIGIN_LOCAL,
    SOURCE_ORIGIN_MIXED,
    SOURCE_ORIGIN_UNKNOWN,
    SOURCE_ORIGINS,
)
from pi_memory.db.models import TranscriptEntry

PREVIEW_CHAR_LIMIT = 1_200
LARGE_FIELD_CHAR_LIMIT = 200
SESSION_EVENT_TYPES = {"session", "session_info", "model_change", "thinking_level_change"}
CUSTOM_EVENT_TYPES = {"custom", "custom_message", "branch_summary"}


@dataclass(frozen=True)
class NormalizedActivity:
    """Pure activity unit ready for future persistence."""

    kind: str
    source_entry_ids: tuple[int, ...]
    byte_start: int
    byte_end: int
    timestamp_start: datetime | None
    timestamp_end: datetime | None
    message_role: str | None
    tool_call_id: str | None
    tool_name: str | None
    is_error: bool | None
    raw_text_available: bool
    text_char_count: int
    result_text_byte_count: int
    result_text_line_count: int
    receipt_json: dict[str, Any]
    source_metadata_json: dict[str, Any]
    sequence: int
    source_origin: str = SOURCE_ORIGIN_LOCAL


@dataclass(frozen=True)
class _OrderedActivity:
    """Activity plus an internal key used to sort by source position."""

    order_byte_start: int
    sequence: int
    activity: NormalizedActivity


@dataclass(frozen=True)
class _PendingToolCall:
    """Assistant tool call awaiting a matching tool result."""

    entry: TranscriptEntry
    block_index: int
    order_byte_start: int
    sequence: int
    tool_call_id: str | None
    tool_name: str | None
    arguments: Any


def normalize_transcript_entries(
    entries: Sequence[TranscriptEntry],
    entry_source_origins: Mapping[int, str] | None = None,
) -> list[NormalizedActivity]:
    """Normalize transcript entries into deterministic structural activities.

    Args:
        entries: Canonical transcript rows to normalize. Rows are sorted by
            ``(byte_start, id or 0)`` before processing.
        entry_source_origins: Optional mapping from database transcript-entry id
            to fork provenance origin.

    Returns:
        Activities in deterministic source-like order. Tool pairs retain the
        original assistant tool-call block position.
    """
    ordered_entries = sorted(entries, key=lambda entry: (entry.byte_start, entry.id or 0))
    activities: list[_OrderedActivity] = []
    pending: dict[str, _PendingToolCall] = {}
    anonymous_pending: list[_PendingToolCall] = []
    sequence = 0

    for entry in ordered_entries:
        payload, metadata = _load_entry_payload(entry)
        if payload is None:
            activities.append(
                _ordered_activity(
                    _activity(
                        kind=ACTIVITY_KIND_CUSTOM_EVENT,
                        entry=entry,
                        source_metadata_json=metadata,
                        sequence=sequence,
                    ),
                    entry.byte_start,
                    sequence,
                ),
            )
            sequence += 1
            continue

        if entry.entry_type == "message":
            if _message_role(payload) == "toolResult":
                tool_call_id = _optional_string(_message(payload).get("toolCallId"))
                call = pending.pop(tool_call_id, None) if tool_call_id is not None else None
                if call is not None:
                    activities.append(_tool_pair_activity(call, entry, payload))
                else:
                    activities.append(_orphan_tool_result_activity(entry, payload, sequence))
                    sequence += 1
                continue

            new_activities, new_pending, sequence = _normalize_message(entry, payload, sequence)
            activities.extend(new_activities)
            for call in new_pending:
                if call.tool_call_id is None:
                    anonymous_pending.append(call)
                else:
                    pending[call.tool_call_id] = call
            continue

        activities.append(_non_message_activity(entry, payload, sequence))
        sequence += 1

    activities.extend(
        _pending_tool_call_activity(call)
        for call in sorted(
            [*pending.values(), *anonymous_pending],
            key=lambda item: (item.order_byte_start, item.sequence),
        )
    )

    normalized = [item.activity for item in sorted(activities, key=lambda item: (item.order_byte_start, item.sequence))]
    if entry_source_origins is None:
        return normalized
    return [_with_source_origin(activity, entry_source_origins) for activity in normalized]


def _with_source_origin(
    activity: NormalizedActivity,
    entry_source_origins: Mapping[int, str],
) -> NormalizedActivity:
    origins_by_entry: dict[str, list[int]] = {}
    for source_entry_id in activity.source_entry_ids:
        origin = entry_source_origins.get(source_entry_id, SOURCE_ORIGIN_UNKNOWN)
        if origin not in SOURCE_ORIGINS:
            origin = SOURCE_ORIGIN_UNKNOWN
        origins_by_entry.setdefault(origin, []).append(source_entry_id)

    if activity.source_entry_ids:
        origins = set(origins_by_entry)
        source_origin = origins.pop() if len(origins) == 1 else SOURCE_ORIGIN_MIXED
    else:
        source_origin = SOURCE_ORIGIN_UNKNOWN
        origins_by_entry = {SOURCE_ORIGIN_UNKNOWN: []}

    metadata = dict(activity.source_metadata_json)
    metadata["source_entry_ids_by_origin"] = origins_by_entry
    return replace(activity, source_origin=source_origin, source_metadata_json=metadata)


def _load_entry_payload(entry: TranscriptEntry) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    try:
        payload = json.loads(entry.raw_line)
    except json.JSONDecodeError as error:
        return None, {
            "entry_type": entry.entry_type,
            "parse_issue": "malformed_json",
            "parse_error": error.msg,
        }

    if not isinstance(payload, dict):
        return None, {
            "entry_type": entry.entry_type,
            "parse_issue": "non_object_json",
            "json_type": type(payload).__name__,
        }

    return payload, {}


def _normalize_message(
    entry: TranscriptEntry,
    payload: dict[str, Any],
    sequence: int,
) -> tuple[list[_OrderedActivity], list[_PendingToolCall], int]:
    message = _message(payload)
    role = _message_role(payload)
    activities: list[_OrderedActivity] = []
    pending: list[_PendingToolCall] = []

    if role == "user":
        char_count = _text_char_count(message.get("content"))
        activities.append(
            _ordered_activity(
                _activity(
                    kind=ACTIVITY_KIND_USER_TEXT,
                    entry=entry,
                    message_role=role,
                    text_char_count=char_count,
                    source_metadata_json={"content": _content_metadata(message.get("content"))},
                    sequence=sequence,
                ),
                entry.byte_start,
                sequence,
            ),
        )
        return activities, pending, sequence + 1

    if role == "assistant":
        for block_index, block in enumerate(_content_blocks(message.get("content"))):
            block_type = _block_type(block)
            if block_type == "text":
                text = _block_text(block)
                activities.append(
                    _ordered_activity(
                        _activity(
                            kind=ACTIVITY_KIND_ASSISTANT_TEXT,
                            entry=entry,
                            message_role=role,
                            text_char_count=len(text),
                            source_metadata_json={
                                "content_index": block_index,
                                "text_preview": _preview(text),
                            },
                            sequence=sequence,
                        ),
                        entry.byte_start,
                        sequence,
                    ),
                )
                sequence += 1
            elif block_type == "thinking":
                text = _block_text(block)
                activities.append(
                    _ordered_activity(
                        _activity(
                            kind=ACTIVITY_KIND_ASSISTANT_THINKING,
                            entry=entry,
                            message_role=role,
                            text_char_count=len(text),
                            source_metadata_json={
                                "content_index": block_index,
                                "text_preview": _preview(text),
                            },
                            sequence=sequence,
                        ),
                        entry.byte_start,
                        sequence,
                    ),
                )
                sequence += 1
            elif block_type == "toolCall":
                call = _tool_call(block)
                pending.append(
                    _PendingToolCall(
                        entry=entry,
                        block_index=block_index,
                        order_byte_start=entry.byte_start,
                        sequence=sequence,
                        tool_call_id=_optional_string(call.get("id")),
                        tool_name=_optional_string(call.get("name")),
                        arguments=call.get("arguments"),
                    ),
                )
                sequence += 1
        return activities, pending, sequence

    activities.append(
        _ordered_activity(
            _activity(
                kind=ACTIVITY_KIND_CUSTOM_EVENT,
                entry=entry,
                message_role=role,
                source_metadata_json={"entry_type": entry.entry_type, "message_role": role},
                sequence=sequence,
            ),
            entry.byte_start,
            sequence,
        ),
    )
    return activities, pending, sequence + 1


def _non_message_activity(entry: TranscriptEntry, payload: dict[str, Any], sequence: int) -> _OrderedActivity:
    if entry.entry_type == "compaction":
        return _ordered_activity(
            _activity(
                kind=ACTIVITY_KIND_COMPACTION,
                entry=entry,
                source_metadata_json=_compaction_metadata(payload),
                sequence=sequence,
            ),
            entry.byte_start,
            sequence,
        )

    if entry.entry_type == "branch_summary":
        return _ordered_activity(
            _activity(
                kind=ACTIVITY_KIND_CUSTOM_EVENT,
                entry=entry,
                source_metadata_json=_branch_summary_metadata(entry, payload),
                sequence=sequence,
            ),
            entry.byte_start,
            sequence,
        )

    kind = ACTIVITY_KIND_SESSION_EVENT if entry.entry_type in SESSION_EVENT_TYPES else ACTIVITY_KIND_CUSTOM_EVENT
    return _ordered_activity(
        _activity(
            kind=kind,
            entry=entry,
            source_metadata_json=_event_metadata(entry, payload),
            sequence=sequence,
        ),
        entry.byte_start,
        sequence,
    )


def _tool_pair_activity(
    call: _PendingToolCall,
    result_entry: TranscriptEntry,
    result_payload: dict[str, Any],
) -> _OrderedActivity:
    message = _message(result_payload)
    result = _result_metadata(message)
    tool_name = call.tool_name or _optional_string(message.get("toolName"))
    receipt = {
        "tool_call_id": call.tool_call_id,
        "tool_name": tool_name,
        "argument_keys": _keys(call.arguments),
        "arguments_preview": _json_preview(call.arguments),
        "is_error": result["is_error"],
        "result_status": result["status"],
        "result_text_byte_count": result["text_byte_count"],
        "result_text_line_count": result["text_line_count"],
        "result_content_types": result["content_types"],
        "details": result["details"],
        "raw_text_available": True,
    }
    byte_start = min(call.entry.byte_start, result_entry.byte_start)
    byte_end = max(call.entry.byte_end, result_entry.byte_end)
    activity = NormalizedActivity(
        kind=ACTIVITY_KIND_TOOL_PAIR,
        source_entry_ids=_source_entry_ids(call.entry, result_entry),
        byte_start=byte_start,
        byte_end=byte_end,
        timestamp_start=_min_timestamp(call.entry.timestamp, result_entry.timestamp),
        timestamp_end=_max_timestamp(call.entry.timestamp, result_entry.timestamp),
        message_role="toolResult",
        tool_call_id=call.tool_call_id,
        tool_name=tool_name,
        is_error=result["is_error"],
        raw_text_available=True,
        text_char_count=0,
        result_text_byte_count=result["text_byte_count"],
        result_text_line_count=result["text_line_count"],
        receipt_json=receipt,
        source_metadata_json={
            "call_content_index": call.block_index,
            "call_entry_id": call.entry.entry_id,
            "result_entry_id": result_entry.entry_id,
        },
        sequence=call.sequence,
    )
    return _ordered_activity(activity, call.order_byte_start, call.sequence)


def _orphan_tool_result_activity(
    entry: TranscriptEntry,
    payload: dict[str, Any],
    sequence: int,
) -> _OrderedActivity:
    message = _message(payload)
    result = _result_metadata(message)
    tool_call_id = _optional_string(message.get("toolCallId"))
    tool_name = _optional_string(message.get("toolName"))
    return _ordered_activity(
        _activity(
            kind=ACTIVITY_KIND_ORPHAN_TOOL_RESULT,
            entry=entry,
            message_role="toolResult",
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            is_error=result["is_error"],
            result_text_byte_count=result["text_byte_count"],
            result_text_line_count=result["text_line_count"],
            receipt_json={
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "is_error": result["is_error"],
                "result_status": result["status"],
                "result_text_byte_count": result["text_byte_count"],
                "result_text_line_count": result["text_line_count"],
                "result_content_types": result["content_types"],
                "details": result["details"],
                "raw_text_available": True,
            },
            sequence=sequence,
        ),
        entry.byte_start,
        sequence,
    )


def _pending_tool_call_activity(call: _PendingToolCall) -> _OrderedActivity:
    activity = _activity(
        kind=ACTIVITY_KIND_PENDING_TOOL_CALL,
        entry=call.entry,
        message_role="assistant",
        tool_call_id=call.tool_call_id,
        tool_name=call.tool_name,
        receipt_json={
            "tool_call_id": call.tool_call_id,
            "tool_name": call.tool_name,
            "argument_keys": _keys(call.arguments),
            "arguments_preview": _json_preview(call.arguments),
            "raw_text_available": True,
        },
        source_metadata_json={
            "call_content_index": call.block_index,
            "call_entry_id": call.entry.entry_id,
        },
        sequence=call.sequence,
    )
    return _ordered_activity(activity, call.order_byte_start, call.sequence)


def _activity(
    *,
    kind: str,
    entry: TranscriptEntry,
    sequence: int,
    message_role: str | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
    is_error: bool | None = None,
    text_char_count: int = 0,
    result_text_byte_count: int = 0,
    result_text_line_count: int = 0,
    receipt_json: dict[str, Any] | None = None,
    source_metadata_json: dict[str, Any] | None = None,
) -> NormalizedActivity:
    return NormalizedActivity(
        kind=kind,
        source_entry_ids=_source_entry_ids(entry),
        byte_start=entry.byte_start,
        byte_end=entry.byte_end,
        timestamp_start=entry.timestamp,
        timestamp_end=entry.timestamp,
        message_role=message_role,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        is_error=is_error,
        raw_text_available=True,
        text_char_count=text_char_count,
        result_text_byte_count=result_text_byte_count,
        result_text_line_count=result_text_line_count,
        receipt_json=receipt_json or {},
        source_metadata_json=source_metadata_json or {},
        sequence=sequence,
    )


def _ordered_activity(activity: NormalizedActivity, order_byte_start: int, sequence: int) -> _OrderedActivity:
    return _OrderedActivity(order_byte_start=order_byte_start, sequence=sequence, activity=activity)


def _message(payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("message")
    if isinstance(message, dict):
        return message
    return {}


def _message_role(payload: dict[str, Any]) -> str | None:
    return _optional_string(_message(payload).get("role"))


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _source_entry_ids(*entries: TranscriptEntry) -> tuple[int, ...]:
    return tuple(entry.id for entry in entries if entry.id is not None)


def _content_blocks(content: Any) -> list[Any]:
    if isinstance(content, list):
        return content
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return []


def _block_type(block: Any) -> str | None:
    if isinstance(block, dict):
        return _optional_string(block.get("type"))
    if isinstance(block, str):
        return "text"
    return None


def _block_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    if not isinstance(block, dict):
        return ""
    for key in ("text", "thinking", "content"):
        value = block.get(key)
        if isinstance(value, str):
            return value
    return ""


def _tool_call(block: Any) -> dict[str, Any]:
    if not isinstance(block, dict):
        return {}
    nested = block.get("toolCall")
    if isinstance(nested, dict):
        return nested
    return block


def _text_char_count(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(_block_text(block)) for block in content if _block_type(block) == "text")
    return 0


def _content_metadata(content: Any) -> dict[str, Any]:
    blocks = _content_blocks(content)
    return {
        "content_types": [_block_type(block) or type(block).__name__ for block in blocks],
        "text_char_count": _text_char_count(content),
    }


def _result_metadata(message: dict[str, Any]) -> dict[str, Any]:
    content = message.get("content")
    text_fragments = _text_fragments(content)
    return {
        "is_error": _is_error(message),
        "status": _result_status(message),
        "text_byte_count": sum(len(fragment.encode("utf-8")) for fragment in text_fragments),
        "text_line_count": sum(_line_count(fragment) for fragment in text_fragments),
        "content_types": _content_types(content),
        "details": _details_metadata(message.get("details")),
    }


def _text_fragments(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        fragments: list[str] = []
        for item in value:
            if isinstance(item, str):
                fragments.append(item)
            elif isinstance(item, dict):
                item_type = item.get("type")
                text = _block_text(item)
                if item_type in {"text", "output", "error"} and text:
                    fragments.append(text)
        return fragments
    if isinstance(value, dict):
        text = _block_text(value)
        return [text] if text else []
    return []


def _content_types(content: Any) -> list[str]:
    if isinstance(content, str):
        return ["text"]
    if isinstance(content, list):
        return [
            _optional_string(item.get("type")) or "object" if isinstance(item, dict) else type(item).__name__
            for item in content
        ]
    if isinstance(content, dict):
        return [_optional_string(content.get("type")) or "object"]
    if content is None:
        return []
    return [type(content).__name__]


def _is_error(message: dict[str, Any]) -> bool | None:
    value = message.get("isError")
    if isinstance(value, bool):
        return value
    status = _optional_string(message.get("status"))
    if status is not None:
        return status.lower() in {"error", "failed", "failure"}
    return None


def _result_status(message: dict[str, Any]) -> str | None:
    status = _optional_string(message.get("status"))
    if status is not None:
        return status
    is_error = _is_error(message)
    if is_error is True:
        return "error"
    if is_error is False:
        return "success"
    return None


def _details_metadata(details: Any) -> dict[str, Any]:
    if not isinstance(details, dict):
        return {}

    scalars: dict[str, Any] = {}
    large_fields: dict[str, dict[str, int]] = {}
    previews: dict[str, dict[str, Any]] = {}
    for key in sorted(details):
        value = details[key]
        if _is_small_scalar(value):
            scalars[key] = value
        elif isinstance(value, str):
            large_fields[key] = {
                "byte_count": len(value.encode("utf-8")),
                "line_count": _line_count(value),
            }
        else:
            previews[key] = _json_preview(value)

    return {
        "keys": sorted(details),
        "scalars": scalars,
        "large_fields": large_fields,
        "previews": previews,
    }


def _is_small_scalar(value: Any) -> bool:
    if value is None or isinstance(value, bool | int | float):
        return True
    return isinstance(value, str) and len(value) <= LARGE_FIELD_CHAR_LIMIT


def _compaction_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {"entry_type": "compaction"}
    summary = payload.get("summary")
    if isinstance(summary, str):
        metadata["summary"] = _preview(summary)
    for key in ("firstKeptEntryId", "tokensBefore"):
        value = payload.get(key)
        if isinstance(value, str | int | float | bool) or value is None:
            metadata[key] = value
    details = payload.get("details")
    if isinstance(details, dict):
        metadata["details_keys"] = sorted(details)
    return metadata


def _branch_summary_metadata(entry: TranscriptEntry, payload: dict[str, Any]) -> dict[str, Any]:
    metadata = _event_metadata(entry, payload)
    from_id = payload.get("fromId")
    if isinstance(from_id, str):
        metadata["fromId"] = from_id
    summary = payload.get("summary")
    if isinstance(summary, str):
        metadata["summary"] = _preview(summary)
    details = payload.get("details")
    if isinstance(details, dict):
        metadata["details_keys"] = sorted(details)
    from_hook = payload.get("fromHook")
    if isinstance(from_hook, bool):
        metadata["fromHook"] = from_hook
    return metadata


def _event_metadata(entry: TranscriptEntry, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_type": entry.entry_type,
        "entry_id": entry.entry_id,
        "payload_keys": sorted(payload),
    }


def _keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        return sorted(str(key) for key in value)
    return []


def _json_preview(value: Any) -> dict[str, Any]:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _preview(serialized)


def _preview(text: str) -> dict[str, Any]:
    is_truncated = len(text) > PREVIEW_CHAR_LIMIT
    return {
        "preview": text[:PREVIEW_CHAR_LIMIT],
        "char_count": len(text),
        "is_truncated": is_truncated,
    }


def _line_count(text: str) -> int:
    if text == "":
        return 0
    return len(text.splitlines()) or 1


def _min_timestamp(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _max_timestamp(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)
