"""HTTP-over-UDS routes for the Claude Code session-lifecycle daemon.

Short-lived SessionStart/SessionEnd hooks POST here rather than holding a
WebSocket: liveness is the durable ``ended_at`` marker in the store, not a live
connection (a hook process exits the instant it returns). The register body is
the shared :class:`RegisterFrame` contract, so the wire shape is single-sourced
with the identity builder that produces it and ``v``/``type`` validate for free.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI

from ..frames import PROTOCOL_VERSION, RegisterFrame
from .store import SessionStore


def register_claude_routes(app: FastAPI, *, store: SessionStore) -> None:
    """Register the Claude daemon's health + session-lifecycle endpoints on ``app``."""

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "protocol": PROTOCOL_VERSION}

    @app.post("/sessions")
    async def register_session(frame: RegisterFrame) -> dict[str, Any]:
        await asyncio.to_thread(
            store.upsert_session,
            session_id=frame.node_id,
            role=frame.role,
            session_name=frame.session_name,
            cwd=frame.cwd,
            transcript_path=frame.session_file,
            repo=frame.repo,
            worktree_label=frame.worktree_label,
            parent_id=frame.parent_id,
            depth=frame.depth,
        )
        return {"node_id": frame.node_id, "protocol": PROTOCOL_VERSION, "status": "registered"}

    @app.post("/sessions/{session_id}/end")
    async def end_session(session_id: str) -> dict[str, Any]:
        ended = await asyncio.to_thread(store.mark_session_ended, session_id)
        return {"node_id": session_id, "ended": ended}

    @app.get("/sessions")
    async def list_sessions() -> dict[str, Any]:
        return {"sessions": await asyncio.to_thread(store.list_open_sessions)}
