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
#: shape changes so stale daemons are terminated and respawned. Started at 1 (a
#: fresh clean-room contract); bumped to 2 when transcript ingest (POST
#: /sessions/{id}/ingest) was added; bumped to 3 when subagent-sidecar ingest added
#: the ``sweep_sidecars``/``agent_transcript_path`` ingest modes, so a running v2
#: daemon (which would accept the POST but silently ignore the new fields and never
#: store subagent transcripts) is respawned to serve them.
CLAUDE_PROTOCOL_VERSION = 3


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


class TranscriptIngestBody(BaseModel):
    """POST /sessions/{id}/ingest body — trigger a transcript ingest.

    All fields are optional; together they select the ingest mode (see
    :func:`..ingest.ingest_session`):

    - ``transcript_path`` overrides the main path stored at SessionStart (PreCompact
      carries it; SessionEnd does not, so the daemon falls back to the stored path).
    - ``sweep_sidecars`` (SessionEnd) walks ``subagents/`` and ingests every sidecar
      not already stored — the guaranteed backstop.
    - ``agent_transcript_path`` (SubagentStop) targets exactly one just-completed
      sidecar, bypassing the main file.
    - ``reason`` records the trigger (``pre-compact`` | ``session-end`` |
      ``subagent-stop``) for diagnostics.
    """

    transcript_path: str | None = None
    reason: str | None = None
    sweep_sidecars: bool = False
    agent_transcript_path: str | None = None
