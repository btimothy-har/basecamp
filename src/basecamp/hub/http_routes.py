"""Read-only HTTP projection routes for the daemon.

The daemon's GET surface — health plus the run and workstream projections clients
poll. Split out of ``app.py`` to keep each file within the length cap;
the WebSocket coordinator stays in ``app.py``.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from .dashboard.access import DashboardAccess, DashboardUnavailableError
from .frames import PROTOCOL_VERSION
from .registry import Registry
from .store import Store

PublicAgentHandle = Annotated[str, Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")]


def register_http_routes(
    app: FastAPI,
    *,
    store: Store,
    registry: Registry,
    dashboard_access: DashboardAccess | None = None,
) -> None:
    """Register the daemon's read-only GET endpoints on ``app``."""

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "protocol": PROTOCOL_VERSION}

    @app.get("/runs/summary")
    async def runs_summary(root_id: str, limit: int = 5) -> dict[str, Any]:
        return await asyncio.to_thread(store.get_run_summary, root_id, limit=limit)

    if dashboard_access is not None:

        @app.post("/dashboard/bootstrap")
        async def dashboard_bootstrap() -> JSONResponse:
            try:
                return JSONResponse(
                    {"url": dashboard_access.mint_bootstrap_url()},
                    headers={"Cache-Control": "no-store"},
                )
            except DashboardUnavailableError as error:
                raise HTTPException(status_code=503, detail=str(error)) from error

    @app.get("/dashboard/snapshot")
    async def dashboard_snapshot() -> dict[str, Any]:
        return await asyncio.to_thread(store.get_dashboard_snapshot, live_node_ids=registry.live_node_ids())

    @app.get("/dashboard/messages")
    async def dashboard_messages(root_handle: PublicAgentHandle, agent_handle: PublicAgentHandle) -> dict[str, Any]:
        return await asyncio.to_thread(
            store.get_dashboard_messages,
            root_handle=root_handle,
            agent_handle=agent_handle,
        )

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
