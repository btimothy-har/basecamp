"""Read-only HTTP projection routes for the daemon.

The daemon's GET surface — health plus the run/workstream/analysis projections the
companion polls. Split out of ``app.py`` to keep each file within the length cap;
the WebSocket coordinator stays in ``app.py``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, HTTPException

from .frames import PROTOCOL_VERSION
from .registry import Registry
from .store import Store


def register_http_routes(app: FastAPI, *, store: Store, registry: Registry) -> None:
    """Register the daemon's read-only GET endpoints on ``app``."""

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "protocol": PROTOCOL_VERSION}

    @app.get("/sessions")
    async def list_sessions() -> dict[str, Any]:
        return {"sessions": await asyncio.to_thread(store.list_open_sessions)}

    @app.get("/runs/summary")
    async def runs_summary(root_id: str, limit: int = 5) -> dict[str, Any]:
        summary = await asyncio.to_thread(store.get_run_summary, root_id, limit=limit)
        summary["session_active"] = registry.has_connection(root_id)
        return summary

    @app.get("/runs/messages")
    async def runs_messages(root_id: str, agent_handle: str, limit: int = 3) -> dict[str, Any]:
        return await asyncio.to_thread(store.get_run_messages, root_id, agent_handle=agent_handle, limit=limit)

    @app.get("/workstreams")
    async def list_workstreams(
        status: str | None = None,
        repo: str | None = None,
        dossier_path: str | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        return {
            "workstreams": await asyncio.to_thread(
                store.list_workstreams,
                status=status,
                repo=repo,
                dossier_path=dossier_path,
                query=query,
            )
        }

    @app.get("/workstreams/{identifier}")
    async def get_workstream(identifier: str) -> dict[str, Any]:
        ws = await asyncio.to_thread(store.get_workstream_with_agents, identifier)
        if ws is None:
            raise HTTPException(status_code=404)
        return ws

    @app.get("/analysis/{session_id}")
    async def get_analysis(session_id: str) -> dict[str, Any]:
        # Thin read: the analyzer already wrote the final shape. Return the stored
        # sections (camelCase) flattened with the session's provenance/metadata.
        row = await asyncio.to_thread(store.get_analysis, session_id)
        if row is None:
            raise HTTPException(status_code=404)
        sections = json.loads(row.sections_json)
        return {**sections, "sessionId": session_id, "model": row.model, "updatedAt": row.updated_at}
