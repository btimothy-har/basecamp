"""Parse a Claude Code transcript JSONL file into storable DAG nodes.

A transcript is append-only JSON-lines. Two kinds of line appear:

- **DAG nodes** carry a ``uuid`` (and usually a ``parentUuid``): ``user`` /
  ``assistant`` / ``system`` / ``attachment``. These are the conversation graph —
  tool calls and results live inside an assistant/user line's ``message.content``
  blocks, not as separate lines. We keep every one, verbatim.
- **UI / state markers** carry no ``uuid`` (``mode``, ``permission-mode``,
  ``ai-title``, ``last-prompt``, ``queue-operation``, ``file-history-*``). They are
  transient editor state, not conversation, and are skipped.

So the ingest rule is simply *"has a ``uuid`` ⇒ store it"*. Each kept line is
stored verbatim in ``line_json``; only the handful of fields the store routes on
(``parentUuid``, ``logicalParentUuid`` — the compaction bridge —, ``type``,
``isSidechain``, ``timestamp``) are lifted out. ``seq`` is the physical line index
so original file order survives even though reconstruction walks ``parentUuid``.

Parsing is line-by-line and lenient: a blank, malformed, or non-object line is
skipped (best-effort), never fatal — a corrupt tail must not lose the good prefix.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def parse_transcript(path: Path) -> list[dict[str, Any]]:
    """Parse ``path`` into a list of storable node dicts (DAG nodes only)."""

    return list(_iter_nodes(path))


def _iter_nodes(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            node = _parse_line(line, index)
            if node is not None:
                yield node


def _parse_line(line: str, seq: int) -> dict[str, Any] | None:
    raw = line.rstrip("\n")
    if not raw.strip():
        return None
    try:
        obj = json.loads(raw)
    except ValueError:
        logger.warning("skipping malformed transcript line %d", seq)
        return None
    if not isinstance(obj, dict):
        return None
    node_uuid = obj.get("uuid")
    if not isinstance(node_uuid, str) or not node_uuid:
        return None  # UI/state marker without a DAG uuid — not conversation
    return {
        "uuid": node_uuid,
        "parent_uuid": _opt_str(obj.get("parentUuid")),
        "logical_parent_uuid": _opt_str(obj.get("logicalParentUuid")),
        "type": _opt_str(obj.get("type")),
        "is_sidechain": 1 if obj.get("isSidechain") else 0,
        "timestamp": _opt_str(obj.get("timestamp")),
        "seq": seq,
        "line_json": raw,
    }


def _opt_str(value: Any) -> str | None:
    """Return ``value`` when it is a non-empty string, else ``None``.

    ``parentUuid`` is ``null`` on roots (original and each compaction re-root) and
    the other lifted fields are optional, so a missing or non-string value maps to
    NULL rather than fabricating a placeholder.
    """

    return value if isinstance(value, str) and value else None
