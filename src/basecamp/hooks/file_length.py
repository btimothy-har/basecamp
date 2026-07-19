"""PostToolUse hook: warn (never block) when a source file grows past the cap.

Fires after a ``Write``/``Edit`` succeeds, so the file is already on disk. This
reads it, counts its lines, and — for a *source* file over the cap — returns a
non-blocking advisory (``hookSpecificOutput.additionalContext``) telling the agent
to review it. It emits no ``decision`` field, so the tool result is untouched and
the write stands; the cap's rationale lives in the engineering doctrine. Anything
unexpected (missing file, non-source suffix, odd payload) returns ``None`` and the
hook stays silent — the primary channel is the doctrine, this is only a nudge.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: Universal line cap for source files. Split along responsibility seams past this.
LINE_CAP = 500

#: Extensions treated as source code. Data, docs, lockfiles, and config are exempt.
_SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".scala",
        ".swift",
        ".rb",
        ".php",
        ".lua",
        ".jl",
        ".c",
        ".h",
        ".cpp",
        ".cc",
        ".cxx",
        ".hpp",
        ".hh",
        ".cs",
        ".sh",
        ".bash",
        ".zsh",
        ".sql",
    }
)


def _target_path(payload: Mapping[str, Any]) -> Path | None:
    """Resolve the written file's absolute path from the hook payload."""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    raw = tool_input.get("file_path")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        cwd = payload.get("cwd")
        if isinstance(cwd, str) and cwd:
            path = Path(cwd) / path
    return path


def handle_file_length(payload: Mapping[str, Any]) -> str | None:
    """Return a non-blocking advisory when a written source file exceeds the cap."""

    if payload.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return None
    path = _target_path(payload)
    if path is None or path.suffix.lower() not in _SOURCE_SUFFIXES:
        return None
    try:
        lines = len(path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return None
    if lines <= LINE_CAP:
        return None
    context = (
        f"basecamp file-length check: {path.name} is now {lines} lines, over the "
        f"{LINE_CAP}-line cap for source files. Files past the cap should be split "
        "along responsibility seams into focused modules (see the engineering doctrine)."
    )
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": context,
            }
        }
    )
