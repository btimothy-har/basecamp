"""HTTP-over-UDS routes for the Claude Code session-lifecycle daemon.

Short-lived SessionStart/SessionEnd hooks POST here rather than holding a
WebSocket: liveness is a durable ``episodes`` row in the store, not a live
connection (a hook process exits the instant it returns). Register opens an
episode; end closes it; the durable ``sessions`` row is never ended. The wire
bodies are the Claude-owned :mod:`..contract` models — no ``hub/frames``
dependency — so FastAPI validates ``session_id``/``cwd`` for free and the Pi
frame package can be deleted without touching this path.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI

from .contract import CLAUDE_PROTOCOL_VERSION, SessionEndBody, SessionRegisterBody
from .store import SessionStore


def register_claude_routes(app: FastAPI, *, store: SessionStore) -> None:
    """Register the Claude daemon's health + session-lifecycle endpoints on ``app``."""

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

    @app.get("/sessions")
    async def list_sessions() -> dict[str, Any]:
        return {"sessions": await asyncio.to_thread(store.list_open_sessions)}
