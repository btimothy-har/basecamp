"""Claude Code hooks (strictly fail-open).

The plugin's ``hooks.json`` wires the session lifecycle — ``SessionStart`` /
``SessionEnd`` / ``PreCompact`` / ``SubagentStop`` → ``basecamp-hook session-start``
/ ``session-end`` / ``pre-compact`` / ``subagent-stop`` — plus a ``PostToolUse``
``Write``/``Edit``/``MultiEdit`` file-length warn → ``basecamp-hook file-length``.
Each invocation reads the hook JSON from stdin, dispatches to a handler, and *always*
exits 0 — a hook must never block or fail a Claude Code session. A handler may return
a string, which is written to stdout as the hook's JSON response (the file-length warn
uses this for its non-blocking advisory); the lifecycle handlers return ``None`` and
stay silent. Any failure (daemon down, malformed payload, unexpected error) is
swallowed and logged best-effort, so a broken hook degrades to no output rather than a
block.

Handler modules are imported lazily (:func:`_load_handler`), so a hook only pays for
what it uses: the per-edit ``file-length`` warn never imports the session module and
its hub client (httpx/pydantic), which it does not touch.
"""

from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from basecamp.hub.claude.paths import claude_runtime_dir

Handler = Callable[[Mapping[str, Any]], str | None]

#: Session events → the ``basecamp.hooks.session`` attribute that handles them.
#: Resolved lazily so importing this package doesn't pull the hub client.
_SESSION_HANDLERS = {
    "session-start": "handle_session_start",
    "session-end": "handle_session_end",
    "pre-compact": "handle_pre_compact",
    "subagent-stop": "handle_subagent_stop",
}

#: Override seam consulted *before* the lazy loader — tests inject stubs here to
#: stay hermetic (no real socket). Empty in production; the loader supplies the
#: real handlers on demand.
_HANDLERS: dict[str, Handler] = {}


def _load_handler(event: str) -> Handler | None:
    """Import and return the handler for an event, or ``None`` if unknown.

    Lazy on purpose: ``file-length`` imports only :mod:`basecamp.hooks.file_length`
    and never :mod:`basecamp.hooks.session` (→ the hub client → httpx/pydantic).
    """
    if event == "file-length":
        from .file_length import handle_file_length  # noqa: PLC0415  # lazy: skip the session import

        return handle_file_length
    attr = _SESSION_HANDLERS.get(event)
    if attr is not None:
        from . import session  # noqa: PLC0415  # lazy: defer the hub client (httpx/pydantic)

        return getattr(session, attr)
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a hook event. Always returns 0 (fail-open)."""

    args = list(argv) if argv is not None else sys.argv[1:]
    event = args[0] if args else ""
    try:
        payload = _read_payload()
        handler = _HANDLERS.get(event) or _load_handler(event)
        if handler is not None:
            output = handler(payload)
            if output:
                sys.stdout.write(output)
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
