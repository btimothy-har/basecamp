"""Analysis-time reduction — the ONLY place the daemon reads pi content.

Given the reconstructed live branch (``get_raw_pi_thread_nodes(...).live`` — a list
of ``entry_json`` strings, root→leaf), this derives the analyzer's input by:

1. Applying compaction (data-level, no LLM): at the latest ``CompactionEntry`` drop
   the path prefix before ``firstKeptEntryId`` and substitute pi's pre-computed
   ``summary``. The daemon applies a stored marker; it never re-runs compaction.
2. Reducing tool noise: keep user text and the assistant's text/thinking, render
   each tool call as ``[tool: <name>]`` and collapse each tool result to
   ``[result: <name> ok|error]`` + a short preview. Tool payloads (the noise) drop.

This is a leaf subsystem versioned against pi's ``SessionEntry`` shape (see
docs/design/companion-daemon-broker.md §6); the daemon core parses none of it.
"""

from __future__ import annotations

import json
from typing import Any

DEFAULT_TOOL_PREVIEW_BUDGET = 120


def reduce_thread(
    live: list[str],
    *,
    tool_preview_budget: int = DEFAULT_TOOL_PREVIEW_BUDGET,
    include_thinking: bool = True,
) -> str:
    """Reduce a live branch (``entry_json`` root→leaf) to the analyzer's context."""

    entries = [parsed for raw in live if (parsed := _parse_entry(raw)) is not None]
    summary, kept = _apply_latest_compaction(entries)

    lines: list[str] = []
    if summary:
        lines.append(f"[earlier conversation compacted]\n{summary.strip()}")
    for entry in kept:
        rendered = _render_entry(entry, tool_preview_budget, include_thinking=include_thinking)
        if rendered:
            lines.append(rendered)
    return "\n\n".join(lines)


def _parse_entry(raw: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _apply_latest_compaction(entries: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    """Return (summary, kept-tail) for the effective (latest) compaction, if any."""

    last_index = None
    for index, entry in enumerate(entries):
        if entry.get("type") == "compaction":
            last_index = index
    if last_index is None:
        return None, entries

    compaction = entries[last_index]
    summary = compaction.get("summary")
    if not (isinstance(summary, str) and summary.strip()):
        # No usable summary to substitute — keep the full path rather than silently
        # dropping every pre-firstKept turn with nothing in its place.
        return None, entries

    first_kept = compaction.get("firstKeptEntryId")
    cut = None
    if first_kept is not None:
        cut = next((i for i, entry in enumerate(entries) if entry.get("id") == first_kept), None)
    if cut is None:
        cut = last_index + 1
    return summary, entries[cut:]


def _render_entry(entry: dict[str, Any], budget: int, *, include_thinking: bool) -> str | None:
    if entry.get("type") != "message":
        return None
    message = entry.get("message")
    if not isinstance(message, dict):
        return None

    role = message.get("role")
    if role == "user":
        text = _text_from_content(message.get("content"))
        return f"User: {text}" if text else None
    if role == "assistant":
        return _render_assistant(message, include_thinking=include_thinking)
    if role == "toolResult":
        return _render_tool_result(message, budget)
    return None


def _render_assistant(message: dict[str, Any], *, include_thinking: bool) -> str | None:
    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
        return f"Assistant: {text}" if text else None
    if not isinstance(content, list):
        return None

    segments: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "text":
            text = str(item.get("text", "")).strip()
            if text:
                segments.append(text)
        elif item_type == "thinking" and include_thinking:
            thinking = str(item.get("thinking", "")).strip()
            if thinking:
                segments.append(f"(thinking) {thinking}")
        elif item_type == "toolCall":
            segments.append(f"[tool: {item.get('name', '?')}]")
    if not segments:
        return None
    return "Assistant: " + "\n".join(segments)


def _render_tool_result(message: dict[str, Any], budget: int) -> str:
    name = message.get("toolName", "?")
    status = "error" if message.get("isError") else "ok"
    preview = " ".join(_text_from_content(message.get("content")).split())
    if len(preview) > budget:
        preview = preview[:budget].rstrip() + "…"
    head = f"[result: {name} {status}]"
    return f"{head} {preview}" if preview else head


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("type") == "text"]
        return "\n".join(part for part in parts if part).strip()
    return ""
