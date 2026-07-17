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
#: store subagent transcripts) is respawned to serve them; bumped to 4 when the
#: workstream record surface (POST/GET /workstreams…) was added, so a running v3
#: daemon (which has no workstreams table and would 404 those routes) is respawned.
CLAUDE_PROTOCOL_VERSION = 4


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


class WorkstreamCreateBody(BaseModel):
    """POST /workstreams body — create a workstream record.

    ``id`` (``ws_<uuid>``) and ``slug`` are minted by the MCP tool, not the daemon,
    so the daemon stays a pure coordination store; a slug collision on the UNIQUE
    constraint is surfaced as a 409 the tool retries with a fresh slug. ``repo`` is
    where it was created; ``dossier_path`` points at the external Logseq work page.
    Agents attach separately (they carry their own repo/worktree), so no worktree
    path lives on the record. There is no status field — liveness is derived from
    whether an attached session has an open episode.
    """

    id: str
    slug: str
    label: str | None = None
    repo: str | None = None
    dossier_path: str | None = None


class WorkstreamAttachBody(BaseModel):
    """POST /workstreams/{id}/attach body — attach a session (agent) to a workstream.

    Additive and idempotent by session. The attaching session carries its own
    ``repo`` and ``worktree_path`` — this is what makes a workstream multi-worker and
    portable across repos, with no single worktree bound to the record.
    """

    session_id: str
    repo: str | None = None
    worktree_path: str | None = None
