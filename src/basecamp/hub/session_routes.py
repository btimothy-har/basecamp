"""Mutating HTTP routes for the hook-driven session lifecycle.

Kept separate from the read-only projections in ``http_routes.py``: short-lived
Claude Code ``SessionStart``/``SessionEnd`` hooks register and end sessions over
HTTP-over-UDS rather than holding a persistent WebSocket (which would reap the
session the instant the hook process exits). The register body is the shared
``RegisterFrame`` contract — reused verbatim so the wire shape is single-sourced
with the WebSocket register path, and ``v``/``type`` are validated for free.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, HTTPException

from .frames import PROTOCOL_VERSION, RegisterFrame
from .store import DuplicateAgentHandleError, Store


def register_session_routes(app: FastAPI, *, store: Store) -> None:
    """Register the daemon's session-lifecycle POST endpoints on ``app``."""

    @app.post("/sessions")
    async def register_session(frame: RegisterFrame) -> dict[str, Any]:
        try:
            await asyncio.to_thread(
                store.upsert_agent,
                agent_id=frame.node_id,
                parent_id=frame.parent_id,
                sibling_group=frame.sibling_group,
                depth=frame.depth,
                role=frame.role,
                session_name=frame.session_name,
                cwd=frame.cwd,
                agent_handle=frame.agent_handle,
                session_file=frame.session_file,
                repo=frame.repo,
                worktree_label=frame.worktree_label,
            )
        except DuplicateAgentHandleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"node_id": frame.node_id, "protocol": PROTOCOL_VERSION, "status": "registered"}

    @app.post("/sessions/{session_id}/end")
    async def end_session(session_id: str) -> dict[str, Any]:
        ended = await asyncio.to_thread(store.mark_agent_ended, session_id)
        return {"node_id": session_id, "ended": ended}
