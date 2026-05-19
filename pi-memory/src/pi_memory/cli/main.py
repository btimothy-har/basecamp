"""Command-line entry point for pi-memory."""

from __future__ import annotations

import errno
import importlib
import ipaddress
import json
import socket
import urllib.error
import urllib.request
from typing import Any

import click
import uvicorn

from pi_memory.constants import DEFAULT_HOST, DEFAULT_PORT, MEMORY_DB_URL, SERVICE_NAME
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
from pi_memory.quality import QualityReportFilterError, SessionQualityReportInspectionService
from pi_memory.recall import RawTranscriptRecallResult, RawTranscriptSearchResult, RecallSearchService
from pi_memory.server import ServerAlreadyRunningError, ServerState, create_app
from pi_memory.settings import Settings as MemorySettings
from pi_memory.settings import SettingsError

DEFAULT_STATUS_TIMEOUT_SECONDS = 1.0


class NonLoopbackHostError(click.BadParameter):
    """Raised when a service host is not loopback-only."""

    def __init__(self) -> None:
        super().__init__("must resolve to a loopback address")


class NonEmptyStringError(click.BadParameter):
    """Raised when an option value is empty after trimming whitespace."""

    def __init__(self) -> None:
        super().__init__("must not be empty")


class ConflictingInterpretationModelOptionsError(click.UsageError):
    """Raised when mutually exclusive interpretation model options are used."""

    def __init__(self) -> None:
        super().__init__("--clear-interpretation-model cannot be used with --interpretation-model")


class ConflictingToolSummaryModelOptionsError(click.UsageError):
    """Raised when mutually exclusive tool-summary model options are used."""

    def __init__(self) -> None:
        super().__init__("--clear-tool-summary-model cannot be used with --tool-summary-model")


class ConflictingQualityModelOptionsError(click.UsageError):
    """Raised when mutually exclusive quality model options are used."""

    def __init__(self) -> None:
        super().__init__("--clear-quality-model cannot be used with --quality-model")


class ConflictingToolSummaryConcurrencyOptionsError(click.UsageError):
    """Raised when mutually exclusive tool-summary concurrency options are used."""

    def __init__(self) -> None:
        super().__init__("--clear-tool-summary-concurrency cannot be used with --tool-summary-concurrency")


class PortBindError(click.ClickException):
    """Raised when the local service cannot bind its requested port."""

    def __init__(self, *, host: str, port: int, reason: str) -> None:
        super().__init__(f"{SERVICE_NAME} cannot start at {_service_base_url(host=host, port=port)}: {reason}")

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


class QualityReportInspectionNotFoundError(click.ClickException):
    """Raised when the requested quality report does not exist."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Quality report for session {session_id} was not found")


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
    "--interpretation-model",
    callback=lambda _ctx, _param, value: None if value is None else _require_non_empty(value),
    help="Provider-neutral PydanticAI provider:model string to persist.",
)
@click.option(
    "--clear-interpretation-model",
    is_flag=True,
    help="Remove the persisted interpretation model.",
)
@click.option(
    "--tool-summary-model",
    callback=lambda _ctx, _param, value: None if value is None else _require_non_empty(value),
    help="Provider-neutral PydanticAI provider:model string to persist for tool summaries.",
)
@click.option(
    "--clear-tool-summary-model",
    is_flag=True,
    help="Remove the persisted tool-summary model.",
)
@click.option(
    "--quality-model",
    callback=lambda _ctx, _param, value: None if value is None else _require_non_empty(value),
    help="Provider-neutral PydanticAI provider:model string to persist for quality assessment.",
)
@click.option(
    "--clear-quality-model",
    is_flag=True,
    help="Remove the persisted quality model.",
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
    tool_summary_concurrency: int | None,
    *,
    clear_interpretation_model: bool,
    clear_tool_summary_model: bool,
    clear_quality_model: bool,
    clear_tool_summary_concurrency: bool,
    json_output: bool,
) -> None:
    """Inspect or update pi-memory interpreter settings."""
    if clear_interpretation_model and interpretation_model is not None:
        raise ConflictingInterpretationModelOptionsError()
    if clear_tool_summary_model and tool_summary_model is not None:
        raise ConflictingToolSummaryModelOptionsError()
    if clear_quality_model and quality_model is not None:
        raise ConflictingQualityModelOptionsError()
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
    quality_database = Database(db_url)
    try:
        payload = SessionQualityReportInspectionService(database=quality_database).get_by_session_id(session_id)
        if payload is None:
            raise QualityReportInspectionNotFoundError(session_id)
        _emit_quality_report(payload, json_output=json_output)
    finally:
        quality_database.close_if_open()


@main.command("quality-list")
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
@click.option("--repo-name", callback=lambda _ctx, _param, value: _optional_non_empty(value))
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
    repo_name: str | None,
    worktree_label: str | None,
    limit: int,
    offset: int,
    json_output: bool,
) -> None:
    """List quality reports directly from the database."""
    quality_database = Database(db_url)
    try:
        payload = (
            SessionQualityReportInspectionService(database=quality_database)
            .list_reports(
                quality_status=quality_status,
                derivation_status=derivation_status,
                promotable=promotable,
                is_current=is_current,
                repo_name=repo_name,
                worktree_label=worktree_label,
                limit=limit,
                offset=offset,
            )
            .to_payload()
        )
    except QualityReportFilterError as error:
        raise click.ClickException(str(error)) from error
    finally:
        quality_database.close_if_open()
    _emit_quality_report_list(payload, json_output=json_output)


@main.command("quality-sample")
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
@click.option("--repo-name", callback=lambda _ctx, _param, value: _optional_non_empty(value))
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
    repo_name: str | None,
    worktree_label: str | None,
    json_output: bool,
) -> None:
    """Sample quality reports directly from the database."""
    quality_database = Database(db_url)
    try:
        payload = SessionQualityReportInspectionService(database=quality_database).sample_reports(
            count=count,
            quality_status=quality_status,
            derivation_status=derivation_status,
            promotable=promotable,
            is_current=is_current,
            repo_name=repo_name,
            worktree_label=worktree_label,
        )
    except QualityReportFilterError as error:
        raise click.ClickException(str(error)) from error
    finally:
        quality_database.close_if_open()
    _emit_quality_report_list(payload, json_output=json_output)


@main.command("quality-tui")
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
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise PortBindError(host=host, port=port, reason=str(error)) from error

    errors: list[OSError] = []
    seen: set[tuple[int, int, int, Any]] = set()
    for family, socktype, proto, _canonname, sockaddr in addresses:
        key = (family, socktype, proto, sockaddr)
        if key in seen:
            continue
        seen.add(key)
        try:
            with socket.socket(family, socktype, proto) as sock:
                sock.bind(sockaddr)
        except OSError as error:
            if error.errno == errno.EADDRINUSE:
                raise PortBindError.in_use(host=host, port=port) from error
            errors.append(error)

    if not seen:
        raise PortBindError(host=host, port=port, reason="host did not resolve to a bind address")
    if errors and len(errors) == len(seen):
        raise PortBindError(host=host, port=port, reason=str(errors[0])) from errors[0]


def _require_loopback_host(host: str) -> str:
    if _is_loopback_host(host):
        return host
    raise NonLoopbackHostError()


def _require_non_empty(value: str) -> str:
    stripped = value.strip()
    if stripped:
        return stripped
    raise NonEmptyStringError()


def _optional_non_empty(value: str | None) -> str | None:
    return None if value is None else _require_non_empty(value)


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
    return f"{_service_base_url(host=host, port=port)}/v1/status"


def _service_base_url(*, host: str, port: int) -> str:
    return f"http://{_http_host(host)}:{port}"


def _http_host(host: str) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host

    if address.version == 6:
        return f"[{host}]"
    return host


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


def _emit_config(payload: dict[str, str | int | None], *, path: str, json_output: bool) -> None:
    output = {"config_path": path, **payload}
    if json_output:
        click.echo(json.dumps(output, sort_keys=True))
        return

    click.echo("Pi memory config")
    for name, value in output.items():
        click.echo(f"  {name}: {_display_optional(value)}")


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


def _emit_quality_report(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(payload, sort_keys=True))
        return

    click.echo("Session quality report")
    for name, value in payload.items():
        if isinstance(value, dict | list):
            click.echo(f"  {name}: {json.dumps(value, sort_keys=True)}")
        else:
            click.echo(f"  {name}: {value}")


def _emit_quality_report_list(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(payload, sort_keys=True))
        return

    results = payload.get("results")
    reports = results if isinstance(results, list) else []
    pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
    total = pagination.get("total", len(reports))
    click.echo(f"Quality reports ({len(reports)} shown, total {total})")
    for index, report in enumerate(reports, start=1):
        if not isinstance(report, dict):
            continue
        click.echo(
            f"{index}. session={report.get('session_id')} status={report.get('quality_status')} "
            f"current={report.get('is_current')} promotable={report.get('promotable')}",
        )
        click.echo(f"   snapshot={report.get('snapshot_id')} report={report.get('quality_report_id')}")


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


def _display_optional(value: object) -> object:
    return "<unset>" if value is None else value


def _echo_status_field(name: str, service_status: dict[str, Any]) -> None:
    value = service_status.get(name)
    if value is not None:
        click.echo(f"  {name}: {value}")
