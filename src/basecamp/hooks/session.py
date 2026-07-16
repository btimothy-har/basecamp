"""Session lifecycle hook handlers (register on start, ingest + end on stop).

The handlers key off the hook stdin JSON that Claude Code delivers
(``session_id``, ``cwd``, ``transcript_path``, and — on SessionStart —
``agent_type``/``source``; on SessionEnd, ``reason``; on PreCompact,
``transcript_path``; on SubagentStop, ``agent_transcript_path``/``agent_id``).
A subagent never registers as its own session — the hub tracks top-level
sessions — but its transcript *is* ingested, keyed to the parent session.

Transcript content is ingested on PreCompact, SessionEnd, and SubagentStop — the
daemon reads the on-disk JSONL itself, so these handlers only fire the trigger.
The main file is ingested on PreCompact (main only) and SessionEnd (main + a full
sidecar sweep); each subagent sidecar is ingested promptly on its SubagentStop and
skipped by the SessionEnd sweep if already stored.

Liveness is per *episode*, not per session: SessionStart opens an episode
(stamped with its ``source``) and SessionEnd closes it (stamped with its
``reason``). Because a resume or ``/clear`` fires a SessionEnd *and* a matching
SessionStart, both are handled uniformly — the closing/opening pair brackets the
engagement without any special-casing, and the durable session row is never ended.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from basecamp.hub.claude.client import build_register_body, end_session, ingest_transcript, register_session


def _str_field(payload: Mapping[str, Any], key: str) -> str | None:
    """Return a non-empty string payload field, else ``None``.

    Normalizes an empty string to ``None`` (mirroring the identity builder's
    ``_clean``) so an absent ``source``/``reason``/``cwd`` is stored as NULL rather
    than "" if Claude Code ever sends the key with an empty value.
    """

    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def handle_session_start(payload: Mapping[str, Any], *, env: Mapping[str, str] | None = None) -> None:
    """Register a top-level session and open a fresh episode for it."""

    if payload.get("agent_type") == "subagent":
        return
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    cwd = _str_field(payload, "cwd")
    transcript = _str_field(payload, "transcript_path")
    source = _str_field(payload, "source")
    body = build_register_body(
        session_id=session_id,
        cwd=cwd or os.getcwd(),
        transcript_path=transcript,
        source=source,
        env=env,
    )
    register_session(body)


def handle_session_end(payload: Mapping[str, Any]) -> None:
    """Ingest the final transcript, then close the session's open episode.

    Every SessionEnd closes the current episode, stamped with its ``reason`` — a
    ``/clear`` or resume is no longer special-cased, because the paired SessionStart
    opens the next episode. The durable ``sessions`` row is never marked ended.

    Ingest runs *before* the close so the transcript's tail nodes are tagged with
    the engagement that is ending (the ingest route reads the still-open episode).
    The SessionEnd payload carries no ``transcript_path``, so the daemon falls back
    to the path stored at SessionStart. This is the guaranteed sidecar backstop:
    every subagent is complete at session end, so ``sweep_sidecars`` captures any not
    already stored by their SubagentStop. Both calls are best-effort and no-op when
    the daemon is down.
    """

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    reason = _str_field(payload, "reason")
    ingest_transcript(session_id, reason="session-end", sweep_sidecars=True)
    end_session(session_id, reason=reason)


def handle_subagent_stop(payload: Mapping[str, Any]) -> None:
    """Ingest one just-completed subagent sidecar, keyed to its parent session.

    SubagentStop fires per subagent completion with the parent ``session_id`` and the
    finished sidecar's ``agent_transcript_path`` — a guaranteed-complete file, so a
    targeted ingest of that one sidecar carries no partial-read risk from in-flight
    peers. Without a sidecar path there is nothing to target (the SessionEnd sweep is
    the backstop), so we no-op. Best-effort; no-op when the daemon is down.
    """

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    agent_transcript = _str_field(payload, "agent_transcript_path")
    if not agent_transcript:
        return
    transcript = _str_field(payload, "transcript_path")
    ingest_transcript(
        session_id,
        transcript_path=transcript,
        agent_transcript_path=agent_transcript,
        reason="subagent-stop",
    )


def handle_pre_compact(payload: Mapping[str, Any]) -> None:
    """Ingest the transcript before Claude Code compacts it (cheap insurance).

    Compaction is append-only, so a later SessionEnd ingest would capture the same
    nodes anyway; ingesting here only guards against a crash between compaction and
    SessionEnd losing the pre-compaction turns. The PreCompact payload supplies the
    ``transcript_path`` explicitly. Subagents are skipped for the same reason as at
    SessionStart — the hub tracks top-level sessions, not sidechain transcripts.
    """

    if payload.get("agent_type") == "subagent":
        return
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    transcript = _str_field(payload, "transcript_path")
    ingest_transcript(session_id, transcript_path=transcript, reason="pre-compact")
