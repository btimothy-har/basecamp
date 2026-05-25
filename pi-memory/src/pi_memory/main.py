"""Command-line entry point for pi-memory."""

from __future__ import annotations

import importlib

import click
import uvicorn

from pi_memory.backfill import run_raw_backfill
from pi_memory.cli.errors import (
    ConflictingEmbeddingModelOptionsError,
    ConflictingInterpretationModelOptionsError,
    ConflictingQualityModelOptionsError,
    ConflictingToolSummaryConcurrencyOptionsError,
    ConflictingToolSummaryModelOptionsError,
)
from pi_memory.cli.inspection import (
    get_durable_memory_payload,
    get_job_payload,
    get_quality_report_payload,
    get_session_interpretation_payload,
    list_durable_audit_payload,
    list_durable_memories_payload,
    list_memory_projection_records_payload,
    list_quality_reports_payload,
    sample_quality_reports_payload,
    search_recall,
)
from pi_memory.cli.rendering import (
    _emit_backfill_result,
    _emit_config,
    _emit_durable_memory,
    _emit_durable_memory_audit,
    _emit_durable_memory_list,
    _emit_healthy,
    _emit_interpretation,
    _emit_job,
    _emit_memory_projection_list,
    _emit_observe_result,
    _emit_quality_report,
    _emit_quality_report_list,
    _emit_recall_result,
    _emit_unavailable,
)
from pi_memory.cli.service import (
    DEFAULT_STATUS_TIMEOUT_SECONDS,
    StatusProbeError,
    _ensure_port_available,
    _fetch_status,
    _status_url,
)
from pi_memory.cli.validation import (
    _optional_non_empty,
    _require_loopback_host,
    _require_non_empty,
    _run_job_value,
)
from pi_memory.constants import DEFAULT_HOST, DEFAULT_PORT, MEMORY_DB_URL, SERVICE_NAME
from pi_memory.db.database import Database
from pi_memory.infra.job_queue import JobStore, JobStoreError
from pi_memory.infra.job_runner import JobDispatcher, JobRunner, JobRunnerError
from pi_memory.ingest import ObserveInput, TranscriptFileMissingError, TranscriptIngestService
from pi_memory.pipeline.runtime.registry import create_job_registry
from pi_memory.pipeline.stages.process_transcript.enqueue import enqueue_process_transcript_job
from pi_memory.server import ServerAlreadyRunningError, ServerState, create_app
from pi_memory.settings import Settings as MemorySettings
from pi_memory.settings import SettingsError


@click.group()
def main() -> None:
    """Pi memory service."""


@main.group()
def debug() -> None:
    """Inspect internal memory service state."""


@main.command()
@click.option(
    "--interpretation-model",
    callback=lambda _ctx, _param, value: None if value is None else _require_non_empty(value),
    help="PydanticAI provider:model string to persist.",
)
@click.option(
    "--clear-interpretation-model",
    is_flag=True,
    help="Remove the persisted interpretation model.",
)
@click.option(
    "--tool-summary-model",
    callback=lambda _ctx, _param, value: None if value is None else _require_non_empty(value),
    help="PydanticAI provider:model string to persist for tool summaries.",
)
@click.option(
    "--clear-tool-summary-model",
    is_flag=True,
    help="Remove the persisted tool-summary model.",
)
@click.option(
    "--quality-model",
    callback=lambda _ctx, _param, value: None if value is None else _require_non_empty(value),
    help="PydanticAI provider:model string to persist for quality assessment.",
)
@click.option(
    "--clear-quality-model",
    is_flag=True,
    help="Remove the persisted quality model.",
)
@click.option(
    "--embedding-model",
    callback=lambda _ctx, _param, value: None if value is None else _require_non_empty(value),
    help="SentenceTransformer embedding model name to persist for Chroma projection.",
)
@click.option(
    "--clear-embedding-model",
    is_flag=True,
    help="Remove the persisted embedding model override.",
)
@click.option(
    "--tool-summary-concurrency",
    type=click.IntRange(1, 100),
    help="Persist the maximum number of concurrent one-tool summary calls.",
)
@click.option(
    "--clear-tool-summary-concurrency",
    is_flag=True,
    help="Remove the persisted tool-summary concurrency override.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Emit parseable JSON output.",
)
def config(
    interpretation_model: str | None,
    tool_summary_model: str | None,
    quality_model: str | None,
    embedding_model: str | None,
    tool_summary_concurrency: int | None,
    *,
    clear_interpretation_model: bool,
    clear_tool_summary_model: bool,
    clear_quality_model: bool,
    clear_embedding_model: bool,
    clear_tool_summary_concurrency: bool,
    json_output: bool,
) -> None:
    """Inspect or update pi-memory model and concurrency settings."""
    if clear_interpretation_model and interpretation_model is not None:
        raise ConflictingInterpretationModelOptionsError()
    if clear_tool_summary_model and tool_summary_model is not None:
        raise ConflictingToolSummaryModelOptionsError()
    if clear_quality_model and quality_model is not None:
        raise ConflictingQualityModelOptionsError()
    if clear_embedding_model and embedding_model is not None:
        raise ConflictingEmbeddingModelOptionsError()
    if clear_tool_summary_concurrency and tool_summary_concurrency is not None:
        raise ConflictingToolSummaryConcurrencyOptionsError()

    memory_settings = MemorySettings()
    try:
        update_payload: dict[str, str | int | None] = {}
        if clear_interpretation_model:
            update_payload["interpretation_model"] = None
        elif interpretation_model is not None:
            update_payload["interpretation_model"] = interpretation_model
        if clear_tool_summary_model:
            update_payload["tool_summary_model"] = None
        elif tool_summary_model is not None:
            update_payload["tool_summary_model"] = tool_summary_model
        if clear_quality_model:
            update_payload["quality_model"] = None
        elif quality_model is not None:
            update_payload["quality_model"] = quality_model
        if clear_embedding_model:
            update_payload["embedding_model"] = None
        elif embedding_model is not None:
            update_payload["embedding_model"] = embedding_model
        if clear_tool_summary_concurrency:
            update_payload["tool_summary_concurrency"] = None
        elif tool_summary_concurrency is not None:
            update_payload["tool_summary_concurrency"] = tool_summary_concurrency
        if update_payload:
            memory_settings.update(**update_payload)
        _emit_config(memory_settings.as_dict(), path=str(memory_settings.path), json_output=json_output)
    except SettingsError as error:
        raise click.ClickException(str(error)) from error


@main.command()
@click.option(
    "--root",
    "roots",
    multiple=True,
    type=click.Path(path_type=str),
    callback=lambda _ctx, _param, value: tuple(_require_non_empty(root) for root in value),
    help="Transcript root directory or JSONL file to import. May be repeated.",
)
@click.option(
    "--db-url",
    default=MEMORY_DB_URL,
    show_default=True,
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    help="Database URL to backfill.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Discover transcripts and session ids without modifying the database.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Emit parseable JSON output.",
)
def backfill(
    roots: tuple[str, ...],
    db_url: str,
    *,
    dry_run: bool,
    json_output: bool,
) -> None:
    """Import raw local Pi transcript files into SQLite."""
    result = run_raw_backfill(db_url=db_url, roots=None if not roots else roots, dry_run=dry_run)
    _emit_backfill_result(result, json_output=json_output)


@main.command()
@click.option(
    "--session-id",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Pi session id for the transcript observation.",
)
@click.option(
    "--transcript-path",
    required=True,
    type=click.Path(path_type=str),
    help="Path to the local transcript file to observe.",
)
@click.option("--cwd", help="Session working directory metadata.")
@click.option("--worktree-label", help="Worktree label metadata.")
@click.option("--worktree-path", help="Worktree path metadata.")
@click.option("--request-id", help="Request id metadata for this observation.")
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Emit parseable JSON output.",
)
def observe(
    session_id: str,
    transcript_path: str,
    cwd: str | None,
    worktree_label: str | None,
    worktree_path: str | None,
    request_id: str | None,
    *,
    json_output: bool,
) -> None:
    """Observe a local Pi transcript file without running the HTTP service."""
    try:
        result = TranscriptIngestService().observe(
            ObserveInput(
                session_id=session_id,
                transcript_path=transcript_path,
                cwd=cwd,
                worktree_label=worktree_label,
                worktree_path=worktree_path,
                request_id=request_id,
            ),
        )
    except TranscriptFileMissingError as error:
        raise click.ClickException(str(error)) from error

    job = enqueue_process_transcript_job(JobStore(), result)
    _emit_observe_result(result, job_id=None if job is None else job.id, json_output=json_output)


@debug.command()
@click.option(
    "--query",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Search query for indexed raw transcript entries.",
)
@click.option(
    "--db-url",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Database URL containing indexed transcript entries.",
)
@click.option(
    "--limit",
    default=10,
    show_default=True,
    type=click.IntRange(1, 50),
    help="Maximum number of recall results.",
)
@click.option(
    "--session-id",
    callback=lambda _ctx, _param, value: None if value is None else _require_non_empty(value),
    help="Optional Pi session id filter.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Emit parseable JSON output.",
)
def recall(
    query: str,
    db_url: str,
    limit: int,
    session_id: str | None,
    *,
    json_output: bool,
) -> None:
    """Search indexed raw transcript entries without running the HTTP service."""
    result = search_recall(
        query=query,
        db_url=db_url,
        limit=limit,
        session_id=session_id,
    )
    _emit_recall_result(result, json_output=json_output)


@debug.command()
@click.option(
    "--session-id",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Stable Pi session id to inspect.",
)
@click.option(
    "--db-url",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Database URL containing the interpretation snapshot.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Emit parseable JSON output.",
)
def interpretation(session_id: str, db_url: str, *, json_output: bool) -> None:
    """Inspect a session interpretation snapshot directly from the database."""
    payload = get_session_interpretation_payload(session_id=session_id, db_url=db_url)
    _emit_interpretation(payload, json_output=json_output)


@debug.command()
@click.option(
    "--session-id",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Stable Pi session id to inspect.",
)
@click.option(
    "--db-url",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Database URL containing the quality report.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Emit parseable JSON output.",
)
def quality(session_id: str, db_url: str, *, json_output: bool) -> None:
    """Inspect a session quality report directly from the database."""
    payload = get_quality_report_payload(session_id=session_id, db_url=db_url)
    _emit_quality_report(payload, json_output=json_output)


@debug.command("quality-list")
@click.option(
    "--db-url",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Database URL containing quality reports.",
)
@click.option("--status", "quality_status", callback=lambda _ctx, _param, value: _optional_non_empty(value))
@click.option("--derivation-status", callback=lambda _ctx, _param, value: _optional_non_empty(value))
@click.option("--promotable/--not-promotable", default=None)
@click.option("--current/--not-current", "is_current", default=None)
@click.option("--cwd", callback=lambda _ctx, _param, value: _optional_non_empty(value))
@click.option("--worktree-label", callback=lambda _ctx, _param, value: _optional_non_empty(value))
@click.option("--limit", type=click.IntRange(1, 100), default=10, show_default=True)
@click.option("--offset", type=click.IntRange(0), default=0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit parseable JSON output.")
def quality_list(
    db_url: str,
    quality_status: str | None,
    derivation_status: str | None,
    *,
    promotable: bool | None,
    is_current: bool | None,
    cwd: str | None,
    worktree_label: str | None,
    limit: int,
    offset: int,
    json_output: bool,
) -> None:
    """List quality reports directly from the database."""
    payload = list_quality_reports_payload(
        db_url=db_url,
        quality_status=quality_status,
        derivation_status=derivation_status,
        promotable=promotable,
        is_current=is_current,
        cwd=cwd,
        worktree_label=worktree_label,
        limit=limit,
        offset=offset,
    )
    _emit_quality_report_list(payload, json_output=json_output)


@debug.command()
@click.option("--memory-id", required=True, type=int, help="Durable memory row id to inspect.")
@click.option(
    "--db-url",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Database URL containing durable memories.",
)
@click.option("--include-audit", is_flag=True, help="Include durable memory audit events.")
@click.option("--json", "json_output", is_flag=True, help="Emit parseable JSON output.")
def durable(memory_id: int, db_url: str, *, include_audit: bool, json_output: bool) -> None:
    """Inspect a durable memory directly from the database."""
    payload = get_durable_memory_payload(
        memory_id=memory_id,
        db_url=db_url,
        include_audit=include_audit,
    )
    _emit_durable_memory(payload, json_output=json_output)


@debug.command("durable-list")
@click.option(
    "--db-url",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Database URL containing durable memories.",
)
@click.option("--status", callback=lambda _ctx, _param, value: _optional_non_empty(value))
@click.option("--cwd", callback=lambda _ctx, _param, value: _optional_non_empty(value))
@click.option("--worktree-label", callback=lambda _ctx, _param, value: _optional_non_empty(value))
@click.option("--session-id", callback=lambda _ctx, _param, value: _optional_non_empty(value))
@click.option("--limit", type=click.IntRange(1, 100), default=10, show_default=True)
@click.option("--offset", type=click.IntRange(0), default=0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit parseable JSON output.")
def durable_list(
    db_url: str,
    status: str | None,
    cwd: str | None,
    worktree_label: str | None,
    session_id: str | None,
    limit: int,
    offset: int,
    *,
    json_output: bool,
) -> None:
    """List durable memories directly from the database."""
    payload = list_durable_memories_payload(
        db_url=db_url,
        status=status,
        cwd=cwd,
        worktree_label=worktree_label,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    _emit_durable_memory_list(payload, json_output=json_output)


@debug.command("durable-audit")
@click.option("--memory-id", required=True, type=int, help="Durable memory row id to inspect.")
@click.option(
    "--db-url",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Database URL containing durable memories.",
)
@click.option("--limit", type=click.IntRange(1, 100), default=10, show_default=True)
@click.option("--offset", type=click.IntRange(0), default=0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit parseable JSON output.")
def durable_audit(memory_id: int, db_url: str, limit: int, offset: int, *, json_output: bool) -> None:
    """Inspect durable memory audit events directly from the database."""
    payload = list_durable_audit_payload(
        memory_id=memory_id,
        db_url=db_url,
        limit=limit,
        offset=offset,
    )
    _emit_durable_memory_audit(payload, json_output=json_output)


@debug.command("projection-list")
@click.option(
    "--db-url",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Database URL containing memory projection records.",
)
@click.option("--record-type", callback=lambda _ctx, _param, value: _optional_non_empty(value))
@click.option("--layer", "memory_layer", callback=lambda _ctx, _param, value: _optional_non_empty(value))
@click.option("--status", "projection_status", callback=lambda _ctx, _param, value: _optional_non_empty(value))
@click.option("--recall-visible/--not-recall-visible", default=None)
@click.option("--relation-visible/--not-relation-visible", default=None)
@click.option("--limit", type=click.IntRange(1, 100), default=10, show_default=True)
@click.option("--offset", type=click.IntRange(0), default=0, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit parseable JSON output.")
def projection_list(
    db_url: str,
    record_type: str | None,
    memory_layer: str | None,
    projection_status: str | None,
    *,
    recall_visible: bool | None,
    relation_visible: bool | None,
    limit: int,
    offset: int,
    json_output: bool,
) -> None:
    """List memory projection records directly from the database."""
    payload = list_memory_projection_records_payload(
        db_url=db_url,
        record_type=record_type,
        memory_layer=memory_layer,
        projection_status=projection_status,
        recall_visible=recall_visible,
        relation_visible=relation_visible,
        limit=limit,
        offset=offset,
    )
    _emit_memory_projection_list(payload, json_output=json_output)


@debug.command("quality-sample")
@click.option(
    "--db-url",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Database URL containing quality reports.",
)
@click.option("--count", type=click.IntRange(1, 100), default=5, show_default=True)
@click.option("--status", "quality_status", callback=lambda _ctx, _param, value: _optional_non_empty(value))
@click.option("--derivation-status", callback=lambda _ctx, _param, value: _optional_non_empty(value))
@click.option("--promotable/--not-promotable", default=None)
@click.option("--current/--not-current", "is_current", default=None)
@click.option("--cwd", callback=lambda _ctx, _param, value: _optional_non_empty(value))
@click.option("--worktree-label", callback=lambda _ctx, _param, value: _optional_non_empty(value))
@click.option("--json", "json_output", is_flag=True, help="Emit parseable JSON output.")
def quality_sample(
    db_url: str,
    count: int,
    quality_status: str | None,
    derivation_status: str | None,
    *,
    promotable: bool | None,
    is_current: bool | None,
    cwd: str | None,
    worktree_label: str | None,
    json_output: bool,
) -> None:
    """Sample quality reports directly from the database."""
    payload = sample_quality_reports_payload(
        db_url=db_url,
        count=count,
        quality_status=quality_status,
        derivation_status=derivation_status,
        promotable=promotable,
        is_current=is_current,
        cwd=cwd,
        worktree_label=worktree_label,
    )
    _emit_quality_report_list(payload, json_output=json_output)


@debug.command("quality-tui")
@click.option(
    "--db-url",
    callback=lambda _ctx, _param, value: MEMORY_DB_URL if value is None else _require_non_empty(value),
    default=None,
    show_default=MEMORY_DB_URL,
    help="Database URL containing quality reports.",
)
def quality_tui(db_url: str) -> None:
    """Open the quality report Textual dashboard."""
    # Textual is only needed for this command, so avoid loading it for every CLI invocation.
    run_quality_tui = importlib.import_module("pi_memory.tui").run_quality_tui

    run_quality_tui(db_url)


@main.command("run-job", hidden=True)
@click.option("--job-id", required=True, type=int, help="Claimed job id to run.")
@click.option(
    "--run-id",
    callback=lambda _ctx, _param, value: None if value is None else _require_non_empty(value),
    help="Run token for the claimed job. Defaults to PI_MEMORY_JOB_RUN_ID.",
)
@click.option(
    "--db-url",
    callback=lambda _ctx, _param, value: None if value is None else _require_non_empty(value),
    help="Database URL containing the claimed job. Defaults to PI_MEMORY_JOB_DB_URL.",
)
def run_job(job_id: int, run_id: str | None, db_url: str | None) -> None:
    """Run a single claimed background job."""
    resolved_run_id = _run_job_value(run_id, "PI_MEMORY_JOB_RUN_ID")
    resolved_db_url = _run_job_value(db_url, "PI_MEMORY_JOB_DB_URL")
    job_database = Database(resolved_db_url)
    try:
        job = JobRunner(database=job_database, registry=create_job_registry()).run(job_id, resolved_run_id)
    except (JobRunnerError, JobStoreError) as error:
        raise click.ClickException(str(error)) from error
    finally:
        job_database.close_if_open()

    click.echo(f"Job {job.id} completed")


@debug.command("job")
@click.option("--job-id", required=True, type=int, help="Job id to inspect.")
@click.option(
    "--db-url",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Database URL containing the job.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Emit parseable JSON output.",
)
def inspect_job(job_id: int, db_url: str, *, json_output: bool) -> None:
    """Inspect a background job directly from the database."""
    payload = get_job_payload(job_id=job_id, db_url=db_url)
    _emit_job(payload, json_output=json_output)


@main.command()
@click.option(
    "--host",
    callback=lambda _ctx, _param, value: _require_loopback_host(value),
    default=DEFAULT_HOST,
    show_default=True,
    help="Loopback host interface to bind. Defaults to localhost for local Pi sessions.",
)
@click.option(
    "--port",
    default=DEFAULT_PORT,
    show_default=True,
    type=click.IntRange(1024, 65535),
    help="TCP port to bind.",
)
def serve(host: str, port: int) -> None:
    """Run the local Pi memory service."""
    state = ServerState()

    try:
        with state.register(host=host, port=port) as metadata:
            _ensure_port_available(host=host, port=port)
            app = create_app(
                host=host,
                port=port,
                memory_dir=state.memory_dir,
                started_at=metadata.started_at_datetime,
                dispatcher=JobDispatcher(),
                auth_token=metadata.auth_token,
            )
            uvicorn.run(app, host=host, port=port)
    except ServerAlreadyRunningError as error:
        raise click.ClickException(str(error)) from error

    click.echo(f"{SERVICE_NAME} stopped")


@main.command()
@click.option(
    "--host",
    callback=lambda _ctx, _param, value: _require_loopback_host(value),
    default=DEFAULT_HOST,
    show_default=True,
    help="Loopback host interface where the local service is listening.",
)
@click.option(
    "--port",
    default=DEFAULT_PORT,
    show_default=True,
    type=click.IntRange(1024, 65535),
    help="TCP port where the local service is listening.",
)
@click.option(
    "--timeout",
    default=DEFAULT_STATUS_TIMEOUT_SECONDS,
    show_default=True,
    type=click.FloatRange(min=0.001),
    help="Seconds to wait for the local service response.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Emit parseable JSON output.",
)
def status(host: str, port: int, timeout: float, *, json_output: bool) -> None:
    """Report whether the local Pi memory service is healthy."""
    url = _status_url(host=host, port=port)

    try:
        service_status = _fetch_status(url=url, timeout=timeout)
    except StatusProbeError as error:
        _emit_unavailable(url=url, error=str(error), json_output=json_output)
        raise click.exceptions.Exit(1) from error

    _emit_healthy(url=url, service_status=service_status, json_output=json_output)
