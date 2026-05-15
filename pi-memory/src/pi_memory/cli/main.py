"""Command-line entry point for pi-memory."""

from __future__ import annotations

import errno
import ipaddress
import json
import socket
import urllib.error
import urllib.request
from typing import Any

import click
import uvicorn

from pi_memory.constants import DEFAULT_HOST, DEFAULT_PORT, SERVICE_NAME
from pi_memory.db import Database
from pi_memory.ingest import IngestResult, ObserveInput, TranscriptFileMissingError, TranscriptIngestService
from pi_memory.interpretation import SessionInterpretationInspectionService
from pi_memory.jobs import (
    JobDispatcher,
    JobRunner,
    JobRunnerError,
    JobStore,
    JobStoreError,
    enqueue_process_transcript_job,
    serialize_job,
)
from pi_memory.recall import RawTranscriptRecallResult, RawTranscriptSearchResult, RecallSearchService
from pi_memory.server import ServerAlreadyRunningError, ServerState, create_app

DEFAULT_STATUS_TIMEOUT_SECONDS = 1.0


class NonLoopbackHostError(click.BadParameter):
    """Raised when a service host is not loopback-only."""

    def __init__(self) -> None:
        super().__init__("must resolve to a loopback address")


class NonEmptyStringError(click.BadParameter):
    """Raised when an option value is empty after trimming whitespace."""

    def __init__(self) -> None:
        super().__init__("must not be empty")


class PortBindError(click.ClickException):
    """Raised when the local service cannot bind its requested port."""

    def __init__(self, *, host: str, port: int, reason: str) -> None:
        super().__init__(f"{SERVICE_NAME} cannot start at http://{host}:{port}: {reason}")

    @classmethod
    def in_use(cls, *, host: str, port: int) -> PortBindError:
        """Return an error for a port already bound by another process."""
        return cls(host=host, port=port, reason="the port is already in use by another process")


class JobInspectionNotFoundError(click.ClickException):
    """Raised when the requested inspection job does not exist."""

    def __init__(self, job_id: int) -> None:
        super().__init__(f"Job {job_id} was not found")


class SessionInterpretationInspectionNotFoundError(click.ClickException):
    """Raised when the requested session interpretation snapshot does not exist."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Interpretation snapshot for session {session_id} was not found")


class StatusProbeError(Exception):
    """Raised when the local service status probe fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message)

    @classmethod
    def http_status(cls, code: int) -> StatusProbeError:
        """Return an error for an unexpected HTTP response."""
        return cls(f"HTTP {code} from status endpoint")

    @classmethod
    def unavailable(cls, reason: str) -> StatusProbeError:
        """Return an error for an unavailable service."""
        return cls(reason)

    @classmethod
    def timed_out(cls) -> StatusProbeError:
        """Return an error for a timed out status probe."""
        return cls("timed out waiting for status endpoint")

    @classmethod
    def invalid_json(cls) -> StatusProbeError:
        """Return an error for an invalid JSON response."""
        return cls("status endpoint returned invalid JSON")

    @classmethod
    def unexpected_json(cls) -> StatusProbeError:
        """Return an error for an unexpected JSON response shape."""
        return cls("status endpoint returned unexpected JSON")


@click.group()
def main() -> None:
    """Pi memory service."""


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
@click.option("--repo-name", help="Repository name metadata.")
@click.option("--repo-root", help="Repository root metadata.")
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
    repo_name: str | None,
    repo_root: str | None,
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
                repo_name=repo_name,
                repo_root=repo_root,
                worktree_label=worktree_label,
                worktree_path=worktree_path,
                request_id=request_id,
            ),
        )
    except TranscriptFileMissingError as error:
        raise click.ClickException(str(error)) from error

    job = enqueue_process_transcript_job(JobStore(), result)
    _emit_observe_result(result, job_id=None if job is None else job.id, json_output=json_output)


@main.command()
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
    recall_database = Database(db_url)
    try:
        result = RecallSearchService(database=recall_database).search(
            query,
            limit=limit,
            session_id=session_id,
        )
    finally:
        recall_database.close_if_open()

    _emit_recall_result(result, json_output=json_output)


@main.command()
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
    interpretation_database = Database(db_url)
    try:
        payload = SessionInterpretationInspectionService(database=interpretation_database).get_by_session_id(session_id)
        if payload is None:
            raise SessionInterpretationInspectionNotFoundError(session_id)
        _emit_interpretation(payload, json_output=json_output)
    finally:
        interpretation_database.close_if_open()


@main.command("run-job")
@click.option("--job-id", required=True, type=int, help="Claimed job id to run.")
@click.option(
    "--run-id",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Run token for the claimed job.",
)
@click.option(
    "--db-url",
    callback=lambda _ctx, _param, value: _require_non_empty(value),
    required=True,
    help="Database URL containing the claimed job.",
)
def run_job(job_id: int, run_id: str, db_url: str) -> None:
    """Run a single claimed background job."""
    job_database = Database(db_url)
    try:
        job = JobRunner(database=job_database).run(job_id, run_id)
    except (JobRunnerError, JobStoreError) as error:
        raise click.ClickException(str(error)) from error
    finally:
        job_database.close_if_open()

    click.echo(f"Job {job.id} completed")


@main.command("job")
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
    job_database = Database(db_url)
    try:
        job = JobStore(database=job_database).get(job_id)
        if job is None:
            raise JobInspectionNotFoundError(job_id)
        _emit_job(serialize_job(job), json_output=json_output)
    finally:
        job_database.close_if_open()


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


def _ensure_port_available(*, host: str, port: int) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            raise PortBindError.in_use(host=host, port=port) from error
        raise PortBindError(host=host, port=port, reason=str(error)) from error


def _require_loopback_host(host: str) -> str:
    if _is_loopback_host(host):
        return host
    raise NonLoopbackHostError()


def _require_non_empty(value: str) -> str:
    if value.strip():
        return value
    raise NonEmptyStringError()


def _is_loopback_host(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass

    try:
        addresses = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False

    return bool(addresses) and all(ipaddress.ip_address(address[4][0]).is_loopback for address in addresses)


def _status_url(*, host: str, port: int) -> str:
    return f"http://{host}:{port}/v1/status"


def _fetch_status(*, url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raise StatusProbeError.http_status(error.code) from error
    except urllib.error.URLError as error:
        raise StatusProbeError.unavailable(_url_error_reason(error)) from error
    except TimeoutError as error:
        raise StatusProbeError.timed_out() from error
    except OSError as error:
        raise StatusProbeError.unavailable(str(error)) from error

    try:
        data = json.loads(content)
    except json.JSONDecodeError as error:
        raise StatusProbeError.invalid_json() from error

    if not isinstance(data, dict):
        raise StatusProbeError.unexpected_json()
    return data


def _url_error_reason(error: urllib.error.URLError) -> str:
    reason = error.reason
    if isinstance(reason, TimeoutError):
        return "timed out waiting for status endpoint"
    return str(reason)


def _emit_healthy(*, url: str, service_status: dict[str, Any], json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps({"ok": True, "url": url, "status": service_status}, sort_keys=True))
        return

    click.echo(f"{SERVICE_NAME} is healthy at {url}")
    _echo_status_field("version", service_status)
    _echo_status_field("pid", service_status)
    _echo_status_field("uptime_seconds", service_status)
    _echo_status_field("memory_dir", service_status)


def _emit_observe_result(result: IngestResult, *, job_id: int | None, json_output: bool) -> None:
    payload = {
        "session_id": result.session_id,
        "transcript_id": result.transcript_id,
        "observation_id": result.observation_id,
        "entries_ingested": result.entries_ingested,
        "cursor_offset": result.cursor_offset,
        "file_size": result.file_size,
        "observed_at": result.observed_at.isoformat(),
        "malformed_lines": result.malformed_lines,
        "unsupported_lines": result.unsupported_lines,
        "job_id": job_id,
    }

    if json_output:
        click.echo(json.dumps(payload, sort_keys=True))
        return

    click.echo("Observed transcript")
    for name, value in payload.items():
        click.echo(f"  {name}: {value}")


def _emit_job(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(payload, sort_keys=True))
        return

    click.echo("Job")
    for name, value in payload.items():
        click.echo(f"  {name}: {value}")


def _emit_interpretation(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(payload, sort_keys=True))
        return

    click.echo("Session interpretation")
    for name, value in payload.items():
        click.echo(f"  {name}: {value}")


def _emit_recall_result(result: RawTranscriptSearchResult, *, json_output: bool) -> None:
    payload = _recall_payload(result)
    if json_output:
        click.echo(json.dumps(payload, sort_keys=True))
        return

    if not result.results:
        click.echo(f"No recall results for: {result.query}")
        return

    click.echo(f"Recall results for: {result.query}")
    for hit in result.results:
        role = "" if hit.message_role is None else f"/{hit.message_role}"
        click.echo(f"{hit.rank}. session={hit.session_id} score={hit.score:.6g}")
        click.echo(f"   source={hit.transcript_path}:{hit.byte_start}-{hit.byte_end}")
        click.echo(f"   entry={hit.entry_type}{role} transcript_entry_id={hit.transcript_entry_id}")
        click.echo(f"   excerpt={hit.excerpt}")
        click.echo(f"   match={hit.match_reason}")


def _recall_payload(result: RawTranscriptSearchResult) -> dict[str, Any]:
    return {
        "query": result.query,
        "terms": list(result.terms),
        "match_query": result.match_query,
        "result_count": len(result.results),
        "results": [_recall_hit_payload(hit) for hit in result.results],
    }


def _recall_hit_payload(result: RawTranscriptRecallResult) -> dict[str, Any]:
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
        "timestamp": None if result.timestamp is None else result.timestamp.isoformat(),
        "byte_start": result.byte_start,
        "byte_end": result.byte_end,
        "excerpt": result.excerpt,
        "match_reason": result.match_reason,
    }


def _emit_unavailable(*, url: str, error: str, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps({"ok": False, "url": url, "error": error}, sort_keys=True))
        return

    click.echo(f"{SERVICE_NAME} is unavailable at {url}: {error}", err=True)


def _echo_status_field(name: str, service_status: dict[str, Any]) -> None:
    value = service_status.get(name)
    if value is not None:
        click.echo(f"  {name}: {value}")
