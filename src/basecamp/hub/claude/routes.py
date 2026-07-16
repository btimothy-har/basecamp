"""HTTP-over-UDS routes for the Claude Code session-lifecycle daemon.

Short-lived SessionStart/SessionEnd hooks POST here rather than holding a
WebSocket: liveness is a durable ``episodes`` row in the store, not a live
connection (a hook process exits the instant it returns). Register opens an
episode; end closes it; the durable ``sessions`` row is never ended. Ingest is
the one route that touches the transcript itself: the PreCompact/SessionEnd hook
POSTs here and the daemon reads the on-disk JSONL, returning before the
(backgrounded) parse finishes. The wire
bodies are the Claude-owned :mod:`..contract` models — no ``hub/frames``
dependency — so FastAPI validates ``session_id``/``cwd`` for free and the Pi
frame package can be deleted without touching this path.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from .contract import CLAUDE_PROTOCOL_VERSION, SessionEndBody, SessionRegisterBody, TranscriptIngestBody
from .ingest import IngestScheduler
from .store import SessionStore

ScheduleIngest = Callable[..., None]


def register_claude_routes(
    app: FastAPI,
    *,
    store: SessionStore,
    schedule_ingest: ScheduleIngest | None = None,
) -> None:
    """Register the Claude daemon's health + session-lifecycle + ingest endpoints.

    ``schedule_ingest`` is the seam for firing a background transcript ingest;
    when omitted a default :class:`IngestScheduler` over ``store`` is used (tests
    inject a recorder to assert scheduling without touching the filesystem).
    """

    if schedule_ingest is None:
        scheduler = IngestScheduler(store)
        app.state.ingest_scheduler = scheduler
        schedule_ingest = scheduler.schedule

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "protocol": CLAUDE_PROTOCOL_VERSION}

    @app.post("/sessions")
    async def register_session(body: SessionRegisterBody) -> dict[str, Any]:
        await asyncio.to_thread(
            store.upsert_session,
            session_id=body.session_id,
            cwd=body.cwd,
            transcript_path=body.transcript_path,
            repo=body.repo,
            worktree_label=body.worktree_label,
            handle=body.handle,
        )
        await asyncio.to_thread(store.open_episode, session_id=body.session_id, source=body.source)
        return {"session_id": body.session_id, "protocol": CLAUDE_PROTOCOL_VERSION, "status": "registered"}

    @app.post("/sessions/{session_id}/end")
    async def end_session(session_id: str, body: SessionEndBody) -> dict[str, Any]:
        ended = await asyncio.to_thread(store.close_episode, session_id=session_id, reason=body.reason)
        return {"session_id": session_id, "ended": ended}

    @app.post("/sessions/{session_id}/ingest")
    async def ingest_transcript(session_id: str, body: TranscriptIngestBody) -> dict[str, Any]:
        # Resolve path + live episode synchronously (episode may close right after a
        # SessionEnd ingest), then hand the slow file parse to the background scheduler.
        transcript_path = body.transcript_path or await asyncio.to_thread(store.get_transcript_path, session_id)
        # A SubagentStop targets its own sidecar and needs no main path; every other
        # trigger reads the main file, so a missing path there is nothing to ingest.
        if not transcript_path and not body.agent_transcript_path:
            return {"session_id": session_id, "scheduled": False, "reason": "no transcript path"}
        episode_id = await asyncio.to_thread(store.current_episode_id, session_id=session_id)
        schedule_ingest(
            session_id=session_id,
            transcript_path=transcript_path,
            episode_id=episode_id,
            sweep_sidecars=body.sweep_sidecars,
            agent_transcript_path=body.agent_transcript_path,
        )
        return {"session_id": session_id, "scheduled": True}

    @app.get("/sessions")
    async def list_sessions() -> dict[str, Any]:
        return {"sessions": await asyncio.to_thread(store.list_open_sessions)}
