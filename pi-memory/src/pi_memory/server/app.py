"""FastAPI application factory for pi-memory."""

import secrets
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from pi_memory.constants import DEFAULT_HOST, DEFAULT_PORT, MEMORY_DIR, SERVICE_NAME, SERVICE_VERSION
from pi_memory.durable import DurableMemoryFilterError, DurableMemoryInspectionService
from pi_memory.ingest import (
    IngestResult,
    ObserveInput,
    TranscriptFileMissingError,
    TranscriptIngestService,
)
from pi_memory.interpretation import SessionInterpretationInspectionService
from pi_memory.jobs import JobDispatcher, JobStore, enqueue_process_transcript_job, serialize_job
from pi_memory.quality import QualityReportFilterError, SessionQualityReportInspectionService
from pi_memory.recall import RawTranscriptRecallResult, RawTranscriptSearchResult, RecallSearchService

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
QualityStatusQuery = Literal["healthy", "degraded", "failed", "not_assessed", "assessment_failed"]
DerivationStatusQuery = Literal["current", "outdated", "superseded"]
DurableMemoryStatusQuery = Literal["candidate", "promoted", "quarantined", "rejected", "archived"]
ProjectionRecordTypeQuery = Literal["session_claim", "durable_memory"]
MemoryLayerQuery = Literal["short_term", "long_term"]
ProjectionStatusQuery = Literal["pending", "indexed", "stale", "failed", "deleted"]
AuthHeader = Annotated[str | None, Header(alias="Authorization")]
AUTH_HEADER_PREFIX = "Bearer "
DEFAULT_TRANSCRIPT_ROOTS = (
    Path.home() / ".pi" / "sessions",
    Path.home() / ".pi" / "transcripts",
    Path("/tmp/pi"),
)


class ObserveRequest(BaseModel):
    """Request body for observing a Pi transcript file."""

    model_config = ConfigDict(extra="forbid")

    session_id: NonEmptyString
    transcript_path: NonEmptyString
    cwd: NonEmptyString | None = None
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


class TranscriptPathNotAllowedError(Exception):
    """Raised when an observe request points outside allowed transcript roots."""

    def __init__(self, transcript_path: Path, allowed_roots: Sequence[Path]) -> None:
        roots = ", ".join(str(root) for root in allowed_roots)
        super().__init__(f"Transcript path {transcript_path} is outside allowed transcript roots: {roots}")


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
    quality_service: SessionQualityReportInspectionService | None = None,
    durable_memory_service: DurableMemoryInspectionService | None = None,
    auth_token: str | None = None,
    allowed_transcript_roots: Sequence[Path] | None = None,
) -> FastAPI:
    """Create the local Pi memory FastAPI application."""
    service_started_at = datetime.now(UTC) if started_at is None else started_at
    service_memory_dir = memory_dir.expanduser()
    service_auth_token = secrets.token_urlsafe(32) if auth_token is None else auth_token
    service_transcript_roots = _resolved_transcript_roots(allowed_transcript_roots)
    require_auth = _auth_dependency(service_auth_token)
    lifespan = _dispatcher_lifespan(dispatcher) if dispatcher is not None else None

    app = FastAPI(title=SERVICE_NAME, version=SERVICE_VERSION, lifespan=lifespan)
    app.state.started_at = service_started_at
    app.state.host = host
    app.state.port = port
    app.state.memory_dir = service_memory_dir
    app.state.auth_token = service_auth_token
    app.state.allowed_transcript_roots = service_transcript_roots
    app.state.ingest_service = TranscriptIngestService() if ingest_service is None else ingest_service
    app.state.job_store = JobStore() if job_store is None else job_store
    app.state.dispatcher = dispatcher
    app.state.recall_service = RecallSearchService() if recall_service is None else recall_service
    app.state.interpretation_service = (
        SessionInterpretationInspectionService() if interpretation_service is None else interpretation_service
    )
    app.state.quality_service = SessionQualityReportInspectionService() if quality_service is None else quality_service
    app.state.durable_memory_service = (
        DurableMemoryInspectionService() if durable_memory_service is None else durable_memory_service
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        """Return a lightweight health check response."""
        return {"status": "ok"}

    @app.get("/v1/status", dependencies=[Depends(require_auth)])
    def status() -> dict[str, object]:
        """Return service status metadata."""
        now = datetime.now(UTC)
        uptime_seconds = max(0.0, (now - app.state.started_at).total_seconds())
        return {
            "service_name": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "started_at": app.state.started_at.isoformat(),
            "uptime_seconds": uptime_seconds,
            "host": app.state.host,
            "port": app.state.port,
        }

    @app.post("/v1/observe", response_model=ObserveResponse, dependencies=[Depends(require_auth)])
    def observe(request: ObserveRequest) -> dict[str, object]:
        """Observe a Pi transcript file and return ingest diagnostics."""
        try:
            result = app.state.ingest_service.observe(_observe_input(request, app.state.allowed_transcript_roots))
        except TranscriptPathNotAllowedError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except TranscriptFileMissingError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

        job = enqueue_process_transcript_job(app.state.job_store, result)
        return _observe_response(result, job_id=None if job is None else job.id)

    @app.get("/v1/debug/jobs/{job_id}", dependencies=[Depends(require_auth)])
    def get_job(job_id: int) -> dict[str, object]:
        """Return read-only debugging details for a background job."""
        job = app.state.job_store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} was not found")
        return serialize_job(job)

    @app.get("/v1/debug/sessions/{session_id}/interpretation", dependencies=[Depends(require_auth)])
    def get_session_interpretation(session_id: str) -> dict[str, object]:
        """Return the latest safe interpretation snapshot for a Pi session."""
        payload = app.state.interpretation_service.get_by_session_id(session_id)
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail=f"Interpretation snapshot for session {session_id} was not found",
            )
        return payload

    @app.get("/v1/debug/sessions/{session_id}/quality", dependencies=[Depends(require_auth)])
    def get_session_quality(session_id: str) -> dict[str, object]:
        """Return the latest safe quality report for a Pi session."""
        payload = app.state.quality_service.get_by_session_id(session_id)
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail=f"Quality report for session {session_id} was not found",
            )
        return payload

    @app.get("/v1/debug/quality/reports", dependencies=[Depends(require_auth)])
    def list_quality_reports(
        quality_status: QualityStatusQuery | None = None,
        derivation_status: DerivationStatusQuery | None = None,
        *,
        promotable: bool | None = None,
        is_current: bool | None = None,
        cwd: str | None = None,
        worktree_label: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, object]:
        """List safe quality reports for dashboard consumers."""
        try:
            return app.state.quality_service.list_reports(
                quality_status=quality_status,
                derivation_status=derivation_status,
                promotable=promotable,
                is_current=is_current,
                cwd=cwd,
                worktree_label=worktree_label,
                limit=limit,
                offset=offset,
            ).to_payload()
        except QualityReportFilterError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/v1/debug/quality/reports/sample", dependencies=[Depends(require_auth)])
    def sample_quality_reports(
        count: int = 5,
        quality_status: QualityStatusQuery | None = None,
        derivation_status: DerivationStatusQuery | None = None,
        *,
        promotable: bool | None = None,
        is_current: bool | None = None,
        cwd: str | None = None,
        worktree_label: str | None = None,
    ) -> dict[str, object]:
        """Return a safe bounded sample of quality reports."""
        try:
            return app.state.quality_service.sample_reports(
                count=count,
                quality_status=quality_status,
                derivation_status=derivation_status,
                promotable=promotable,
                is_current=is_current,
                cwd=cwd,
                worktree_label=worktree_label,
            )
        except QualityReportFilterError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/v1/debug/durable-memory", dependencies=[Depends(require_auth)])
    def list_durable_memories(
        status: DurableMemoryStatusQuery | None = None,
        cwd: str | None = None,
        worktree_label: str | None = None,
        session_id: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, object]:
        """List safe durable memories for dashboard consumers."""
        try:
            return app.state.durable_memory_service.list_memories(
                status=status,
                cwd=cwd,
                worktree_label=worktree_label,
                session_id=session_id,
                limit=limit,
                offset=offset,
            ).to_payload()
        except DurableMemoryFilterError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/v1/debug/durable-memory/{memory_id}", dependencies=[Depends(require_auth)])
    def get_durable_memory(memory_id: int, *, include_audit: bool = False) -> dict[str, object]:
        """Return one safe durable memory payload."""
        payload = app.state.durable_memory_service.get_memory(memory_id, include_audit=include_audit)
        if payload is None:
            raise HTTPException(status_code=404, detail=f"Durable memory {memory_id} was not found")
        return payload

    @app.get("/v1/debug/durable-memory/{memory_id}/audit", dependencies=[Depends(require_auth)])
    def list_durable_memory_audit_events(
        memory_id: int,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, object]:
        """Return a safe audit timeline for one durable memory."""
        try:
            result = app.state.durable_memory_service.list_audit_events(memory_id, limit=limit, offset=offset)
        except DurableMemoryFilterError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if result is None:
            raise HTTPException(status_code=404, detail=f"Durable memory {memory_id} was not found")
        return result.to_payload()

    @app.get("/v1/debug/memory-projections", dependencies=[Depends(require_auth)])
    def list_memory_projection_records(
        record_type: ProjectionRecordTypeQuery | None = None,
        memory_layer: MemoryLayerQuery | None = None,
        projection_status: ProjectionStatusQuery | None = None,
        *,
        recall_visible: bool | None = None,
        relation_visible: bool | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, object]:
        """List safe memory projection records for dashboard consumers."""
        try:
            return app.state.durable_memory_service.list_projection_records(
                record_type=record_type,
                memory_layer=memory_layer,
                projection_status=projection_status,
                recall_visible=recall_visible,
                relation_visible=relation_visible,
                limit=limit,
                offset=offset,
            ).to_payload()
        except DurableMemoryFilterError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/recall/search", response_model=RecallSearchResponse, dependencies=[Depends(require_auth)])
    def recall_search(request: RecallSearchRequest) -> dict[str, object]:
        """Search indexed raw transcript entries."""
        result = app.state.recall_service.search(
            request.query,
            limit=request.limit,
            session_id=request.session_id,
        )
        return _recall_search_response(result)

    return app


def _auth_dependency(auth_token: str) -> Callable[[AuthHeader], None]:
    def require_auth(authorization: AuthHeader = None) -> None:
        if _is_valid_auth_header(authorization, auth_token):
            return
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return require_auth


def _is_valid_auth_header(authorization: str | None, auth_token: str) -> bool:
    if authorization is None or not authorization.startswith(AUTH_HEADER_PREFIX):
        return False
    candidate = authorization.removeprefix(AUTH_HEADER_PREFIX)
    return secrets.compare_digest(candidate, auth_token)


def _dispatcher_lifespan(dispatcher: JobDispatcher) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        dispatcher.start()
        try:
            yield
        finally:
            dispatcher.stop()

    return lifespan


def _observe_input(request: ObserveRequest, allowed_roots: Sequence[Path]) -> ObserveInput:
    transcript_path = _allowed_transcript_path(request.transcript_path, allowed_roots)
    return ObserveInput(
        session_id=request.session_id,
        transcript_path=transcript_path,
        cwd=request.cwd,
        worktree_label=request.worktree_label,
        worktree_path=request.worktree_path,
        request_id=request.request_id,
        request_metadata=request.request_metadata,
    )


def _allowed_transcript_path(transcript_path: str, allowed_roots: Sequence[Path]) -> Path:
    path = Path(transcript_path).expanduser()
    resolved_path = path.resolve(strict=False)
    if path.suffix != ".jsonl" or not any(_is_relative_to(resolved_path, root) for root in allowed_roots):
        raise TranscriptPathNotAllowedError(resolved_path, allowed_roots)
    return path


def _resolved_transcript_roots(allowed_roots: Sequence[Path] | None) -> tuple[Path, ...]:
    roots = DEFAULT_TRANSCRIPT_ROOTS if allowed_roots is None else allowed_roots
    return tuple(root.expanduser().resolve(strict=False) for root in roots)


def _is_relative_to(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


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
