"""Claude Code lifecycle hooks (strictly fail-open).

The plugin's ``hooks.json`` wires ``SessionStart`` / ``SessionEnd`` to
``basecamp-hook session-start`` / ``session-end``. Each invocation reads the
hook JSON from stdin, dispatches to a handler, and *always* exits 0 — a hook
must never block or fail a Claude Code session. Any failure (daemon down,
malformed payload, unexpected error) is swallowed and logged best-effort.
"""

from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from basecamp.hub.claude.paths import claude_runtime_dir

from .session import handle_session_end, handle_session_start

_HANDLERS = {
    "session-start": handle_session_start,
    "session-end": handle_session_end,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a hook event. Always returns 0 (fail-open)."""

    args = list(argv) if argv is not None else sys.argv[1:]
    event = args[0] if args else ""
    try:
        payload = _read_payload()
        handler = _HANDLERS.get(event)
        if handler is not None:
            handler(payload)
    except Exception:  # noqa: BLE001 - hooks must never break a session
        _log_failure(event)
    return 0


def _read_payload() -> Mapping[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def _log_failure(event: str) -> None:
    try:
        log_path = claude_runtime_dir() / "hooks.log"
        log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = datetime.now(UTC).isoformat()
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"--- {stamp} event={event or '<none>'} ---\n")
            handle.write(traceback.format_exc())
            handle.write("\n")
    except OSError:
        pass
