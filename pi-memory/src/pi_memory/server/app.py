"""FastAPI application factory for pi-memory."""

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from pi_memory.constants import DEFAULT_HOST, DEFAULT_PORT, MEMORY_DIR, SERVICE_NAME, SERVICE_VERSION
from pi_memory.ingest import (
    IngestResult,
    ObserveInput,
    TranscriptFileMissingError,
    TranscriptIngestService,
)
from pi_memory.interpretation import SessionInterpretationInspectionService
from pi_memory.jobs import JobDispatcher, JobStore, enqueue_process_transcript_job, serialize_job
from pi_memory.recall import RawTranscriptRecallResult, RawTranscriptSearchResult, RecallSearchService

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
    observation_id: int
    entries_ingested: int
    cursor_offset: int
    file_size: int
    observed_at: datetime
    malformed_lines: int
    unsupported_lines: int
    job_id: int | None


class RecallSearchRequest(BaseModel):
    """Request body for searching indexed raw transcript entries."""

    model_config = ConfigDict(extra="forbid")

    query: NonEmptyString
    limit: int = Field(default=10, ge=1, le=50)
    session_id: NonEmptyString | None = None


class RecallSearchHitResponse(BaseModel):
    """Source-backed raw transcript recall hit."""

    result_type: Literal["raw_transcript"]
    rank: int
    score: float
    session_id: str
    transcript_id: int
    transcript_path: str
    transcript_entry_id: int
    pi_entry_id: str | None
    entry_type: str
    message_role: str | None
    timestamp: datetime | None
    byte_start: int
    byte_end: int
    excerpt: str
    match_reason: str


class RecallSearchResponse(BaseModel):
    """Response body for raw transcript recall search."""

    query: str
    terms: list[str]
    match_query: str | None
    result_count: int
    results: list[RecallSearchHitResponse]


def create_app(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    memory_dir: Path = MEMORY_DIR,
    started_at: datetime | None = None,
    ingest_service: TranscriptIngestService | None = None,
    job_store: JobStore | None = None,
    dispatcher: JobDispatcher | None = None,
    recall_service: RecallSearchService | None = None,
    interpretation_service: SessionInterpretationInspectionService | None = None,
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
    app.state.job_store = JobStore() if job_store is None else job_store
    app.state.dispatcher = dispatcher
    app.state.recall_service = RecallSearchService() if recall_service is None else recall_service
    app.state.interpretation_service = (
        SessionInterpretationInspectionService() if interpretation_service is None else interpretation_service
    )

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
    def observe(request: ObserveRequest) -> dict[str, object]:
        """Observe a Pi transcript file and return ingest diagnostics."""
        try:
            result = app.state.ingest_service.observe(_observe_input(request))
        except TranscriptFileMissingError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

        job = enqueue_process_transcript_job(app.state.job_store, result)
        return _observe_response(result, job_id=None if job is None else job.id)

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: int) -> dict[str, object]:
        """Return read-only debugging details for a background job."""
        job = app.state.job_store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} was not found")
        return serialize_job(job)

    @app.get("/v1/sessions/{session_id}/interpretation")
    def get_session_interpretation(session_id: str) -> dict[str, object]:
        """Return the latest safe interpretation snapshot for a Pi session."""
        payload = app.state.interpretation_service.get_by_session_id(session_id)
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail=f"Interpretation snapshot for session {session_id} was not found",
            )
        return payload

    @app.post("/v1/recall/search", response_model=RecallSearchResponse)
    def recall_search(request: RecallSearchRequest) -> dict[str, object]:
        """Search indexed raw transcript entries."""
        result = app.state.recall_service.search(
            request.query,
            limit=request.limit,
            session_id=request.session_id,
        )
        return _recall_search_response(result)

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


def _observe_response(result: IngestResult, *, job_id: int | None) -> dict[str, object]:
    return {
        "session_id": result.session_id,
        "transcript_id": result.transcript_id,
        "observation_id": result.observation_id,
        "entries_ingested": result.entries_ingested,
        "cursor_offset": result.cursor_offset,
        "file_size": result.file_size,
        "observed_at": result.observed_at,
        "malformed_lines": result.malformed_lines,
        "unsupported_lines": result.unsupported_lines,
        "job_id": job_id,
    }


def _recall_search_response(result: RawTranscriptSearchResult) -> dict[str, object]:
    return {
        "query": result.query,
        "terms": list(result.terms),
        "match_query": result.match_query,
        "result_count": len(result.results),
        "results": [_recall_search_hit_response(hit) for hit in result.results],
    }


def _recall_search_hit_response(result: RawTranscriptRecallResult) -> dict[str, object]:
    return {
        "result_type": result.result_type,
        "rank": result.rank,
        "score": result.score,
        "session_id": result.session_id,
        "transcript_id": result.transcript_id,
        "transcript_path": result.transcript_path,
        "transcript_entry_id": result.transcript_entry_id,
        "pi_entry_id": result.pi_entry_id,
        "entry_type": result.entry_type,
        "message_role": result.message_role,
        "timestamp": result.timestamp,
        "byte_start": result.byte_start,
        "byte_end": result.byte_end,
        "excerpt": result.excerpt,
        "match_reason": result.match_reason,
    }
