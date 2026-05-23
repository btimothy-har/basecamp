"""CLI database inspection helpers."""

from __future__ import annotations

from typing import Any

import click

from pi_memory.cli.errors import (
    DurableMemoryInspectionNotFoundError,
    JobInspectionNotFoundError,
    QualityReportInspectionNotFoundError,
    SessionInterpretationInspectionNotFoundError,
)
from pi_memory.db.database import Database
from pi_memory.durable import DurableMemoryFilterError, DurableMemoryInspectionService
from pi_memory.infra.job_queue import JobStore, serialize_job
from pi_memory.interpretation import SessionInterpretationInspectionService
from pi_memory.quality import QualityReportFilterError, SessionQualityReportInspectionService
from pi_memory.recall import RawTranscriptSearchResult, RecallSearchService


def search_recall(
    *,
    query: str,
    db_url: str,
    limit: int,
    session_id: str | None,
) -> RawTranscriptSearchResult:
    recall_database = Database(db_url)
    try:
        return RecallSearchService(database=recall_database).search(
            query,
            limit=limit,
            session_id=session_id,
        )
    finally:
        recall_database.close_if_open()


def get_session_interpretation_payload(*, session_id: str, db_url: str) -> dict[str, Any]:
    interpretation_database = Database(db_url)
    try:
        payload = SessionInterpretationInspectionService(database=interpretation_database).get_by_session_id(session_id)
        if payload is None:
            raise SessionInterpretationInspectionNotFoundError(session_id)
        return payload
    finally:
        interpretation_database.close_if_open()


def get_quality_report_payload(*, session_id: str, db_url: str) -> dict[str, Any]:
    quality_database = Database(db_url)
    try:
        payload = SessionQualityReportInspectionService(database=quality_database).get_by_session_id(session_id)
        if payload is None:
            raise QualityReportInspectionNotFoundError(session_id)
        return payload
    finally:
        quality_database.close_if_open()


def list_quality_reports_payload(
    *,
    db_url: str,
    quality_status: str | None,
    derivation_status: str | None,
    promotable: bool | None,
    is_current: bool | None,
    cwd: str | None,
    worktree_label: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    quality_database = Database(db_url)
    try:
        return (
            SessionQualityReportInspectionService(database=quality_database)
            .list_reports(
                quality_status=quality_status,
                derivation_status=derivation_status,
                promotable=promotable,
                is_current=is_current,
                cwd=cwd,
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


def get_durable_memory_payload(
    *,
    memory_id: int,
    db_url: str,
    include_audit: bool,
) -> dict[str, Any]:
    durable_database = Database(db_url)
    try:
        payload = DurableMemoryInspectionService(database=durable_database).get_memory(
            memory_id,
            include_audit=include_audit,
        )
        if payload is None:
            raise DurableMemoryInspectionNotFoundError(memory_id)
        return payload
    finally:
        durable_database.close_if_open()


def list_durable_memories_payload(
    *,
    db_url: str,
    status: str | None,
    cwd: str | None,
    worktree_label: str | None,
    session_id: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    durable_database = Database(db_url)
    try:
        return (
            DurableMemoryInspectionService(database=durable_database)
            .list_memories(
                status=status,
                cwd=cwd,
                worktree_label=worktree_label,
                session_id=session_id,
                limit=limit,
                offset=offset,
            )
            .to_payload()
        )
    except DurableMemoryFilterError as error:
        raise click.ClickException(str(error)) from error
    finally:
        durable_database.close_if_open()


def list_durable_audit_payload(
    *,
    memory_id: int,
    db_url: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    durable_database = Database(db_url)
    try:
        result = DurableMemoryInspectionService(database=durable_database).list_audit_events(
            memory_id,
            limit=limit,
            offset=offset,
        )
        if result is None:
            raise DurableMemoryInspectionNotFoundError(memory_id)
        return result.to_payload()
    except DurableMemoryFilterError as error:
        raise click.ClickException(str(error)) from error
    finally:
        durable_database.close_if_open()


def list_memory_projection_records_payload(
    *,
    db_url: str,
    record_type: str | None,
    memory_layer: str | None,
    projection_status: str | None,
    recall_visible: bool | None,
    relation_visible: bool | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    projection_database = Database(db_url)
    try:
        return (
            DurableMemoryInspectionService(database=projection_database)
            .list_projection_records(
                record_type=record_type,
                memory_layer=memory_layer,
                projection_status=projection_status,
                recall_visible=recall_visible,
                relation_visible=relation_visible,
                limit=limit,
                offset=offset,
            )
            .to_payload()
        )
    except DurableMemoryFilterError as error:
        raise click.ClickException(str(error)) from error
    finally:
        projection_database.close_if_open()


def sample_quality_reports_payload(
    *,
    db_url: str,
    count: int,
    quality_status: str | None,
    derivation_status: str | None,
    promotable: bool | None,
    is_current: bool | None,
    cwd: str | None,
    worktree_label: str | None,
) -> dict[str, Any]:
    quality_database = Database(db_url)
    try:
        return SessionQualityReportInspectionService(database=quality_database).sample_reports(
            count=count,
            quality_status=quality_status,
            derivation_status=derivation_status,
            promotable=promotable,
            is_current=is_current,
            cwd=cwd,
            worktree_label=worktree_label,
        )
    except QualityReportFilterError as error:
        raise click.ClickException(str(error)) from error
    finally:
        quality_database.close_if_open()


def get_job_payload(*, job_id: int, db_url: str) -> dict[str, Any]:
    job_database = Database(db_url)
    try:
        job = JobStore(database=job_database).get(job_id)
        if job is None:
            raise JobInspectionNotFoundError(job_id)
        return serialize_job(job)
    finally:
        job_database.close_if_open()
