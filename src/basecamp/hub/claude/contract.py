"""Claude-owned HTTP request contract for the session-lifecycle daemon.

Deliberately independent of the shared ``hub/frames/`` package: the Claude
session hooks POST these bodies to the daemon, and nothing here is derived from
the Pi swarm wire. Keeping the register/end shapes local means retiring the Pi
side is a straight deletion of ``hub/frames/`` — no Claude edit required.

``CLAUDE_PROTOCOL_VERSION`` is the daemon-compatibility gate returned by
``GET /health``; a client that expects a different version treats the running
daemon as incompatible and respawns it (see ``client/spawn.py``).
"""

from __future__ import annotations

from pydantic import BaseModel

#: Compatibility gate for the Claude hub daemon. Bump when the register/end wire
#: shape changes so stale daemons are terminated and respawned. Starts at 1: a
#: fresh clean-room contract, not a continuation of the shared frame version.
CLAUDE_PROTOCOL_VERSION = 1


class SessionRegisterBody(BaseModel):
    """POST /sessions body — a top-level Claude Code session registering itself.

    ``source`` is the SessionStart source (``startup`` | ``clear`` | ``resume`` |
    ``compact``); stored verbatim as the opening episode's ``source``. ``handle`` is
    a durable addressable name reserved for later — unpopulated this increment.
    """

    session_id: str
    cwd: str
    transcript_path: str | None = None
    repo: str | None = None
    worktree_label: str | None = None
    handle: str | None = None
    source: str | None = None


class SessionEndBody(BaseModel):
    """POST /sessions/{id}/end body — the SessionEnd reason, stored as ``end_reason``."""

    reason: str | None = None
