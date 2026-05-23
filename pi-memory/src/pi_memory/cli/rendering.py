"""CLI output rendering helpers."""

from __future__ import annotations

import json
from typing import Any

import click

from pi_memory.constants import SERVICE_NAME
from pi_memory.ingest import IngestResult
from pi_memory.recall import RawTranscriptRecallResult, RawTranscriptSearchResult


def _emit_healthy(*, url: str, service_status: dict[str, Any], json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps({"ok": True, "url": url, "status": service_status}, sort_keys=True))
        return

    click.echo(f"{SERVICE_NAME} is healthy at {url}")
    _echo_status_field("version", service_status)
    _echo_status_field("uptime_seconds", service_status)
    _echo_status_field("host", service_status)
    _echo_status_field("port", service_status)


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


def _emit_durable_memory(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(payload, sort_keys=True))
        return

    click.echo("Durable memory")
    for name, value in payload.items():
        if isinstance(value, dict | list):
            click.echo(f"  {name}: {json.dumps(value, sort_keys=True)}")
        else:
            click.echo(f"  {name}: {value}")


def _emit_durable_memory_list(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(payload, sort_keys=True))
        return

    results = payload.get("results")
    memories = results if isinstance(results, list) else []
    pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
    total = pagination.get("total", len(memories))
    click.echo(f"Durable memories ({len(memories)} shown, total {total})")
    for index, memory in enumerate(memories, start=1):
        if not isinstance(memory, dict):
            continue
        click.echo(
            f"{index}. memory={memory.get('memory_id')} session={memory.get('session_id')} "
            f"status={memory.get('status')} kind={memory.get('claim_kind')}",
        )
        click.echo(f"   statement={memory.get('statement')}")


def _emit_durable_memory_audit(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(payload, sort_keys=True))
        return

    results = payload.get("results")
    events = results if isinstance(results, list) else []
    pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
    total = pagination.get("total", len(events))
    click.echo(f"Durable memory audit events ({len(events)} shown, total {total})")
    for index, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            continue
        click.echo(
            f"{index}. event={event.get('event_id')} memory={event.get('memory_id')} "
            f"type={event.get('event_type')} {event.get('from_status')}->{event.get('to_status')}",
        )
        click.echo(f"   reason={event.get('reason_code')} created_at={event.get('created_at')}")


def _emit_memory_projection_list(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(payload, sort_keys=True))
        return

    results = payload.get("results")
    records = results if isinstance(results, list) else []
    pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
    total = pagination.get("total", len(records))
    click.echo(f"Memory projection records ({len(records)} shown, total {total})")
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            continue
        click.echo(
            f"{index}. projection={record.get('projection_record_id')} type={record.get('record_type')} "
            f"layer={record.get('memory_layer')} status={record.get('status')}",
        )
        click.echo(f"   record_key={record.get('record_key')} chroma_id={record.get('chroma_id')}")


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
