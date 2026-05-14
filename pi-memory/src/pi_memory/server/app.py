"""FastAPI application factory for pi-memory."""

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints

from pi_memory.constants import DEFAULT_HOST, DEFAULT_PORT, MEMORY_DIR, SERVICE_NAME, SERVICE_VERSION
from pi_memory.ingest import (
    IngestResult,
    ObserveInput,
    TranscriptFileMissingError,
    TranscriptIngestService,
)
from pi_memory.jobs import JobDispatcher

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ObserveRequest(BaseModel):
    """Request body for observing a Pi transcript file."""

    model_config = ConfigDict(extra="forbid")

    session_id: NonEmptyString
    transcript_path: NonEmptyString
    cwd: NonEmptyString | None = None
    repo_name: NonEmptyString | None = None
    repo_root: NonEmptyString | None = None
    worktree_label: NonEmptyString | None = None
    worktree_path: NonEmptyString | None = None
    request_id: NonEmptyString | None = None
    request_metadata: dict[str, Any] | None = None


class ObserveResponse(BaseModel):
    """Diagnostics returned after observing a Pi transcript file."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    transcript_id: int
    entries_ingested: int
    cursor_offset: int
    file_size: int
    observed_at: datetime
    malformed_lines: int
    unsupported_lines: int


def create_app(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    memory_dir: Path = MEMORY_DIR,
    started_at: datetime | None = None,
    ingest_service: TranscriptIngestService | None = None,
    dispatcher: JobDispatcher | None = None,
) -> FastAPI:
    """Create the local Pi memory FastAPI application."""
    service_started_at = datetime.now(UTC) if started_at is None else started_at
    service_memory_dir = memory_dir.expanduser()
    lifespan = _dispatcher_lifespan(dispatcher) if dispatcher is not None else None

    app = FastAPI(title=SERVICE_NAME, version=SERVICE_VERSION, lifespan=lifespan)
    app.state.started_at = service_started_at
    app.state.host = host
    app.state.port = port
    app.state.memory_dir = service_memory_dir
    app.state.ingest_service = TranscriptIngestService() if ingest_service is None else ingest_service
    app.state.dispatcher = dispatcher

    @app.get("/health")
    def health() -> dict[str, str]:
        """Return a lightweight health check response."""
        return {"status": "ok"}

    @app.get("/v1/status")
    def status() -> dict[str, object]:
        """Return process and service status metadata."""
        now = datetime.now(UTC)
        uptime_seconds = max(0.0, (now - app.state.started_at).total_seconds())
        return {
            "service_name": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "pid": os.getpid(),
            "started_at": app.state.started_at.isoformat(),
            "uptime_seconds": uptime_seconds,
            "host": app.state.host,
            "port": app.state.port,
            "memory_dir": str(app.state.memory_dir),
        }

    @app.post("/v1/observe", response_model=ObserveResponse)
    def observe(request: ObserveRequest) -> IngestResult:
        """Observe a Pi transcript file and return ingest diagnostics."""
        try:
            return app.state.ingest_service.observe(_observe_input(request))
        except TranscriptFileMissingError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return app


def _dispatcher_lifespan(dispatcher: JobDispatcher) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        dispatcher.start()
        try:
            yield
        finally:
            dispatcher.stop()

    return lifespan


def _observe_input(request: ObserveRequest) -> ObserveInput:
    return ObserveInput(
        session_id=request.session_id,
        transcript_path=request.transcript_path,
        cwd=request.cwd,
        repo_name=request.repo_name,
        repo_root=request.repo_root,
        worktree_label=request.worktree_label,
        worktree_path=request.worktree_path,
        request_id=request.request_id,
        request_metadata=request.request_metadata,
    )
