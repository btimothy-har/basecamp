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
import logging
import sqlite3
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException

from .contract import (
    CLAUDE_PROTOCOL_VERSION,
    SessionEndBody,
    SessionRegisterBody,
    TranscriptIngestBody,
    WorkstreamCreateBody,
    WorkstreamStatusBody,
    WorkstreamWorktreeBody,
)
from .ingest import IngestScheduler
from .store import SessionStore

logger = logging.getLogger(__name__)

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
        # ``close_episode`` is a write, and the SessionEnd hook fires the (backgrounded)
        # sidecar-sweep ingest immediately before this /end. Under WAL readers no longer
        # block, but SQLite is still single-writer, so this UPDATE can wait behind the
        # in-flight ingest write up to ``busy_timeout`` and then raise. Unguarded that is
        # a 500 the fail-open client reads as ``ended: false`` — and unlike a delayed
        # ingest the episode's ``end_reason`` is then lost for good (the next
        # ``open_episode`` force-closes it with a NULL reason). Degrade explicitly, the
        # same way /ingest does, rather than surfacing an unhandled error.
        try:
            ended = await asyncio.to_thread(store.close_episode, session_id=session_id, reason=body.reason)
        except sqlite3.OperationalError:
            logger.warning("session end not recorded: store busy closing episode for %s", session_id)
            return {"session_id": session_id, "ended": False, "reason": "store busy"}
        return {"session_id": session_id, "ended": ended}

    @app.post("/sessions/{session_id}/ingest")
    async def ingest_transcript(session_id: str, body: TranscriptIngestBody) -> dict[str, Any]:
        # Resolve path + live episode synchronously (episode may close right after a
        # SessionEnd ingest), then hand the slow file parse to the background scheduler.
        # WAL keeps these reads from blocking behind an in-flight ingest write, but a
        # contended lock can still time out; degrade to an explicit not-scheduled reply
        # rather than a 500 the fail-open client would silently read as "not scheduled".
        try:
            transcript_path = body.transcript_path or await asyncio.to_thread(store.get_transcript_path, session_id)
            episode_id = await asyncio.to_thread(store.current_episode_id, session_id=session_id)
        except sqlite3.OperationalError:
            logger.warning("ingest not scheduled: store busy resolving session %s", session_id)
            return {"session_id": session_id, "scheduled": False, "reason": "store busy"}
        # A SubagentStop targets its own sidecar and needs no main path; every other
        # trigger reads the main file, so a missing path there is nothing to ingest.
        if not transcript_path and not body.agent_transcript_path:
            return {"session_id": session_id, "scheduled": False, "reason": "no transcript path"}
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

    @app.post("/workstreams", status_code=201)
    async def create_workstream(body: WorkstreamCreateBody) -> dict[str, Any]:
        # The MCP tool mints id + slug; a slug collision on the UNIQUE constraint is a
        # 409 the tool retries with a fresh slug. IntegrityError is caught separately
        # from the OperationalError store-busy degrade below — the two mean different
        # things (duplicate vs contended write) and map to different statuses.
        try:
            return await asyncio.to_thread(
                store.create_workstream,
                workstream_id=body.id,
                slug=body.slug,
                label=body.label,
                repo=body.repo,
                worktree_path=body.worktree_path,
                dossier_path=body.dossier_path,
            )
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="slug or id already exists") from None
        except sqlite3.OperationalError:
            logger.warning("workstream not created: store busy")
            raise HTTPException(status_code=503, detail="store busy") from None

    @app.get("/workstreams")
    async def list_workstreams(repo: str | None = None, status: str | None = None) -> dict[str, Any]:
        rows = await asyncio.to_thread(store.list_workstreams, repo=repo, status=status)
        return {"workstreams": rows}

    @app.get("/workstreams/by-worktree")
    async def get_workstream_by_worktree(path: str) -> dict[str, Any]:
        row = await asyncio.to_thread(store.get_workstream_by_worktree, path)
        if row is None:
            raise HTTPException(status_code=404, detail="no workstream for that worktree")
        return row

    @app.get("/workstreams/{identifier}")
    async def get_workstream(identifier: str) -> dict[str, Any]:
        row = await asyncio.to_thread(store.get_workstream, identifier)
        if row is None:
            raise HTTPException(status_code=404, detail="workstream not found")
        return row

    @app.post("/workstreams/{identifier}/status")
    async def set_workstream_status(identifier: str, body: WorkstreamStatusBody) -> dict[str, Any]:
        try:
            changed = await asyncio.to_thread(store.set_workstream_status, identifier, body.status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid status: {body.status!r}") from None
        except sqlite3.OperationalError:
            logger.warning("workstream status not updated: store busy for %s", identifier)
            raise HTTPException(status_code=503, detail="store busy") from None
        if not changed:
            raise HTTPException(status_code=404, detail="workstream not found")
        return {"identifier": identifier, "status": body.status, "updated": True}

    @app.post("/workstreams/{identifier}/worktree")
    async def set_workstream_worktree(identifier: str, body: WorkstreamWorktreeBody) -> dict[str, Any]:
        try:
            changed = await asyncio.to_thread(store.set_workstream_worktree, identifier, body.worktree_path)
        except sqlite3.OperationalError:
            logger.warning("workstream worktree not persisted: store busy for %s", identifier)
            raise HTTPException(status_code=503, detail="store busy") from None
        if not changed:
            raise HTTPException(status_code=404, detail="workstream not found")
        return {"identifier": identifier, "worktree_path": body.worktree_path, "updated": True}

    @app.delete("/workstreams/{identifier}")
    async def delete_workstream(identifier: str) -> dict[str, Any]:
        deleted = await asyncio.to_thread(store.delete_workstream, identifier)
        if not deleted:
            raise HTTPException(status_code=404, detail="workstream not found")
        return {"identifier": identifier, "deleted": True}
