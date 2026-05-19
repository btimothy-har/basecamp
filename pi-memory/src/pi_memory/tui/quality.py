"""Quality report Textual application seam and read-only dashboard data loader."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, Footer, Header, Static

from pi_memory.db import (
    JOB_KIND_INTERPRET_SESSION,
    JOB_STATUS_FAILED,
    Database,
    Job,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    Transcript,
)

QualityDashboardRowType = Literal["quality_report", "interpretation_failure"]
QualityFilterMode = Literal["all", "healthy", "degraded", "failures"]

QUALITY_FAILURE_STATUSES = {"assessment_failed", "failed"}
QUALITY_STATUSES = ("healthy", "degraded", "not_assessed", "assessment_failed", "failed")
TABLE_COLUMNS = (
    ("type", 22, "type"),
    ("status", 18, "status"),
    ("promotable", 10, "promotable"),
    ("session", 18, "session"),
    ("transcript", 18, "transcript"),
    ("reason/error", 42, "reason"),
    ("findings", 12, "findings"),
    ("ref defects", 11, "ref_defects"),
    ("updated", 20, "updated"),
)
MAX_DETAIL_FINDINGS = 8
MAX_METADATA_ITEMS = 8


@dataclass(frozen=True)
class QualityDashboardRow:
    """A normalized row for the quality dashboard table."""

    row_id: str
    row_type: QualityDashboardRowType
    session_id: str | None
    transcript_id: int | None
    transcript_path: str | None
    repo_name: str | None
    worktree_label: str | None
    status: str
    reason: str | None
    semantic_status: str | None
    deterministic_status: str | None
    promotable: bool | None
    finding_counts: dict[str, int]
    reference_defect_count: int
    updated_at: datetime | None
    interpretation_job_id: int | None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QualityDashboardData:
    """Data and aggregate metrics needed by the quality dashboard."""

    rows: list[QualityDashboardRow]
    transcript_count: int
    quality_report_count: int
    row_count: int
    quality_status_counts: dict[str, int]
    promotable_count: int
    non_promotable_count: int
    failed_interpretation_count: int
    quality_reference_defect_report_count: int
    quality_reference_defect_count: int


def load_quality_dashboard_data(db_url: str) -> QualityDashboardData:
    """Load quality dashboard data from an existing pi-memory database.

    The loader is intentionally read-only: it opens its own database engine, does
    not initialize or migrate the schema, and only executes SELECT queries.

    Args:
        db_url: SQLAlchemy database URL for an existing final-schema database.

    Returns:
        Normalized rows and aggregate metrics for the dashboard.
    """
    quality_database = Database(db_url)
    try:
        with Session(quality_database.engine) as db_session:
            transcript_count = _load_transcript_count(db_session)
            report_rows = _load_quality_report_rows(db_session)
            failure_rows = _load_interpretation_failure_rows(db_session, report_rows)
    finally:
        quality_database.close_if_open()

    rows = [*report_rows, *failure_rows]
    rows.sort(key=_row_sort_key, reverse=True)
    return _dashboard_data(rows, transcript_count=transcript_count, quality_report_count=len(report_rows))


class QualityTuiApp(App[None]):
    """Single-screen quality report dashboard."""

    TITLE = "pi-memory quality"
    SUB_TITLE = "Quality report dashboard"
    BINDINGS = [
        ("a", "show_all", "all"),
        ("h", "show_healthy", "healthy"),
        ("d", "show_degraded", "degraded"),
        ("f", "show_failures", "failures"),
        ("p", "toggle_promotable", "promotable"),
        ("r", "reload", "reload"),
        ("q", "quit", "quit"),
    ]
    CSS = """
    #quality-screen {
        layout: vertical;
    }

    #quality-metrics {
        height: auto;
        padding: 0 1;
    }

    #quality-help {
        height: 1;
        padding: 0 1;
    }

    #quality-table {
        height: 1fr;
    }

    #quality-detail {
        height: 16;
        border: solid $accent;
        padding: 0 1;
    }
    """

    def __init__(self, db_url: str) -> None:
        super().__init__()
        self.db_url = db_url
        self.data: QualityDashboardData | None = None
        self._filter_mode: QualityFilterMode = "all"
        self._promotable_only = False
        self._rows_by_key: dict[str, QualityDashboardRow] = {}

    def compose(self) -> ComposeResult:
        """Compose the quality dashboard."""
        yield Header()
        with Container(id="quality-screen"):
            yield Static("Loading quality dashboard...", id="quality-metrics")
            yield Static(self._help_text(), id="quality-help")
            yield DataTable(id="quality-table")
            yield Static("Select a row to show details.", id="quality-detail")
        yield Footer()

    def on_mount(self) -> None:
        """Load data and configure the table after widgets are mounted."""
        table = self.query_one("#quality-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        self._reload_data()

    def action_show_all(self) -> None:
        """Show all rows."""
        self._filter_mode = "all"
        self._refresh_dashboard()

    def action_show_healthy(self) -> None:
        """Show healthy quality reports."""
        self._filter_mode = "healthy"
        self._refresh_dashboard()

    def action_show_degraded(self) -> None:
        """Show degraded quality reports."""
        self._filter_mode = "degraded"
        self._refresh_dashboard()

    def action_show_failures(self) -> None:
        """Show interpretation and assessment failures."""
        self._filter_mode = "failures"
        self._refresh_dashboard()

    def action_toggle_promotable(self) -> None:
        """Toggle promotable-only filtering."""
        self._promotable_only = not self._promotable_only
        self._refresh_dashboard()

    def action_reload(self) -> None:
        """Reload dashboard data from the database."""
        self._reload_data()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Update the detail pane for the highlighted row."""
        self._show_row_detail(event.row_key.value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Update the detail pane for the selected row."""
        self._show_row_detail(event.row_key.value)

    def _reload_data(self) -> None:
        self.data = load_quality_dashboard_data(self.db_url)
        self._refresh_dashboard()

    def _refresh_dashboard(self) -> None:
        self.query_one("#quality-metrics", Static).update(self._metrics_text())
        self.query_one("#quality-help", Static).update(self._help_text())
        rows = self._filtered_rows()
        self._populate_table(rows)
        if rows:
            self.query_one("#quality-table", DataTable).move_cursor(row=0, column=0)
            self._show_row_detail(rows[0].row_id)
        else:
            self.query_one("#quality-detail", Static).update("No rows match the current filters.")

    def _populate_table(self, rows: list[QualityDashboardRow]) -> None:
        table = self.query_one("#quality-table", DataTable)
        table.clear(columns=True)
        for label, width, key in TABLE_COLUMNS:
            table.add_column(label, width=width, key=key)
        self._rows_by_key = {row.row_id: row for row in rows}
        for row in rows:
            table.add_row(*self._table_cells(row), key=row.row_id)

    def _filtered_rows(self) -> list[QualityDashboardRow]:
        if self.data is None:
            return []
        rows = [row for row in self.data.rows if self._matches_mode(row)]
        if self._promotable_only:
            return [row for row in rows if row.promotable is True]
        return rows

    def _matches_mode(self, row: QualityDashboardRow) -> bool:
        if self._filter_mode == "all":
            return True
        if self._filter_mode == "healthy":
            return row.row_type == "quality_report" and row.status == "healthy"
        if self._filter_mode == "degraded":
            return row.row_type == "quality_report" and row.status == "degraded"
        if self._filter_mode == "failures":
            return row.row_type == "interpretation_failure" or row.status in QUALITY_FAILURE_STATUSES
        return True

    def _metrics_text(self) -> str:
        if self.data is None:
            return "Loading quality dashboard..."
        counts = self.data.quality_status_counts
        status_counts = "  ".join(f"{status}: {counts.get(status, 0)}" for status in QUALITY_STATUSES)
        totals = (
            f"Transcripts: {self.data.transcript_count}  "
            f"Reports: {self.data.quality_report_count}  Rows: {self.data.row_count}"
        )
        return "\n".join(
            (
                f"Database: {self.db_url}",
                totals,
                status_counts,
                "  ".join(
                    (
                        f"promotable: {self.data.promotable_count}",
                        f"not promotable/no report: {self.data.non_promotable_count}",
                        f"failed interpretations: {self.data.failed_interpretation_count}",
                        "ref-defect reports/refs: "
                        f"{self.data.quality_reference_defect_report_count}/"
                        f"{self.data.quality_reference_defect_count}",
                    ),
                ),
            ),
        )

    def _help_text(self) -> str:
        promotable = "on" if self._promotable_only else "off"
        return (
            "a all | h healthy | d degraded | f failures | p promotable-only "
            f"({promotable}) | r reload | q quit | filter: {self._filter_mode}"
        )

    def _table_cells(self, row: QualityDashboardRow) -> tuple[str, ...]:
        return (
            row.row_type,
            row.status,
            _format_bool_value(row.promotable),
            _compact(row.session_id),
            _transcript_label(row),
            _truncate(row.reason or "", 80),
            _finding_counts_label(row.finding_counts),
            str(row.reference_defect_count),
            _format_datetime(row.updated_at),
        )

    def _show_row_detail(self, row_id: str) -> None:
        row = self._rows_by_key.get(row_id)
        if row is None:
            return
        self.query_one("#quality-detail", Static).update(_detail_text(row))


def _detail_text(row: QualityDashboardRow) -> str:
    lines = [
        f"{row.row_type}  status={row.status}  promotable={_format_bool_value(row.promotable)}",
        f"session={_display(row.session_id)}  transcript={_display(row.transcript_id)}",
        f"path={_display(row.transcript_path)}",
        f"repo={_display(row.repo_name)}  worktree={_display(row.worktree_label)}",
        f"reason/error={_display(row.reason)}",
    ]
    if row.row_type == "quality_report":
        lines.extend(_quality_detail_lines(row))
    else:
        lines.extend(_failure_detail_lines(row))
    return "\n".join(lines)


def _quality_detail_lines(row: QualityDashboardRow) -> list[str]:
    detail = row.detail
    claim_count = len(_as_list(detail.get("claim_assessments")))
    missing_count = len(_as_list(detail.get("missing_high_signal_items")))
    lines = [
        (f"deterministic={_display(row.deterministic_status)}  semantic={_display(row.semantic_status)}"),
        (
            f"quality_report_id={_display(detail.get('quality_report_id'))}  "
            f"snapshot_id={_display(detail.get('snapshot_id'))}"
        ),
        (
            f"snapshot_status={_display(detail.get('snapshot_status'))}  "
            f"derivation={_display(detail.get('derivation_status'))}"
        ),
        (
            f"snapshot_job={_display(detail.get('snapshot_job_id'))}  "
            f"quality_job={_display(detail.get('quality_job_id'))}"
        ),
        f"claims={claim_count}  missing_items={missing_count}",
        (
            f"prompt_version={_display(detail.get('prompt_version'))}  "
            f"schema_version={_display(detail.get('schema_version'))}"
        ),
        (f"created={_format_datetime_value(detail.get('created_at'))}  updated={_format_datetime(row.updated_at)}"),
    ]
    lines.extend(_finding_detail_lines("deterministic findings", _as_list(detail.get("deterministic_findings"))))
    lines.extend(_finding_detail_lines("semantic findings", _as_list(detail.get("semantic_findings"))))
    lines.append(f"assessment metadata: {_format_mapping(_as_dict(detail.get('assessment_metadata')))}")
    lines.append(f"model metadata: {_format_mapping(_as_dict(detail.get('model_metadata')))}")
    return lines


def _failure_detail_lines(row: QualityDashboardRow) -> list[str]:
    detail = row.detail
    lines = [
        (
            f"job_id={_display(detail.get('job_id'))}  "
            f"kind={_display(detail.get('job_kind'))}  "
            f"status={_display(detail.get('job_status'))}"
        ),
        (
            f"attempts={_display(detail.get('attempts'))}/"
            f"{_display(detail.get('max_attempts'))}  "
            f"run_id={_display(detail.get('run_id'))}  "
            f"exit_code={_display(detail.get('exit_code'))}"
        ),
        (
            f"created={_format_datetime_value(detail.get('created_at'))}  "
            f"updated={_format_datetime(row.updated_at)}  "
            f"finished={_format_datetime_value(detail.get('finished_at'))}"
        ),
        f"last_error={_display(detail.get('last_error'))}",
        f"payload: {_format_mapping(_as_dict(detail.get('payload')))}",
        f"result: {_format_mapping(_as_dict(detail.get('result')))}",
    ]
    return lines


def _finding_detail_lines(label: str, findings: list[Any]) -> list[str]:
    if not findings:
        return [f"{label}: 0"]
    lines = [f"{label}: {len(findings)}"]
    lines.extend(f"  - {_finding_label(finding)}" for finding in findings[:MAX_DETAIL_FINDINGS])
    if len(findings) > MAX_DETAIL_FINDINGS:
        lines.append(f"  ... {len(findings) - MAX_DETAIL_FINDINGS} more")
    return lines


def _finding_label(finding: Any) -> str:
    if not isinstance(finding, dict):
        return _truncate(str(finding), 160)
    severity = _display(finding.get("severity"))
    code = _display(finding.get("code"))
    message = _display(finding.get("message") or finding.get("description"))
    return _truncate(f"{severity} {code}: {message}", 180)


def _format_mapping(mapping: dict[str, Any]) -> str:
    if not mapping:
        return "n/a"
    items = list(mapping.items())
    parts = [f"{key}={_format_scalar(value)}" for key, value in items[:MAX_METADATA_ITEMS]]
    if len(items) > MAX_METADATA_ITEMS:
        parts.append(f"... {len(items) - MAX_METADATA_ITEMS} more")
    return _truncate(", ".join(parts), 240)


def _format_scalar(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, datetime):
        return _format_datetime(value)
    if isinstance(value, str | int | float | bool):
        return str(value)
    return json.dumps(value, default=str, sort_keys=True)


def _transcript_label(row: QualityDashboardRow) -> str:
    if row.transcript_id is not None:
        return str(row.transcript_id)
    if row.transcript_path:
        return _compact(row.transcript_path)
    return "n/a"


def _finding_counts_label(counts: dict[str, int]) -> str:
    return f"c:{counts.get('critical', 0)} w:{counts.get('warning', 0)} i:{counts.get('info', 0)}"


def _format_bool_value(value: Any) -> str:
    if value is None:
        return "n/a"
    return "yes" if value is True else "no"


def _display(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    return _truncate(_format_scalar(value), 160)


def _compact(value: str | None) -> str:
    if not value:
        return "n/a"
    return _truncate(value, 24)


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1]}…"


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "n/a"
    return value.isoformat(timespec="seconds")


def _format_datetime_value(value: Any) -> str:
    if isinstance(value, datetime):
        return _format_datetime(value)
    return _display(value)


def run_quality_tui(db_url: str) -> None:
    """Run the quality report TUI.

    Args:
        db_url: Database URL containing quality report data.
    """
    QualityTuiApp(db_url).run()


def _load_transcript_count(db_session: Session) -> int:
    return int(db_session.scalar(select(func.count()).select_from(Transcript)) or 0)


def _load_quality_report_rows(db_session: Session) -> list[QualityDashboardRow]:
    rows = db_session.execute(
        select(
            SessionInterpretationQualityReport,
            SessionInterpretationSnapshot,
            MemorySession,
            Transcript,
        )
        .join(
            SessionInterpretationSnapshot,
            SessionInterpretationQualityReport.snapshot_id == SessionInterpretationSnapshot.id,
        )
        .join(MemorySession, SessionInterpretationSnapshot.session_id == MemorySession.id)
        .outerjoin(Transcript, SessionInterpretationSnapshot.transcript_id == Transcript.id),
    ).all()

    return [
        _quality_report_row(
            report=report,
            snapshot=snapshot,
            memory_session=memory_session,
            transcript=transcript,
        )
        for report, snapshot, memory_session, transcript in rows
    ]


def _quality_report_row(
    *,
    report: SessionInterpretationQualityReport,
    snapshot: SessionInterpretationSnapshot,
    memory_session: MemorySession,
    transcript: Transcript | None,
) -> QualityDashboardRow:
    deterministic_findings = _as_list(report.deterministic_findings_json)
    semantic_findings = _as_list(report.semantic_findings_json)
    assessment_metadata = _as_dict(report.assessment_metadata_json)
    reference_defect_count = _reference_defect_count(assessment_metadata)
    return QualityDashboardRow(
        row_id=f"quality-report:{report.id}",
        row_type="quality_report",
        session_id=memory_session.session_id,
        transcript_id=snapshot.transcript_id,
        transcript_path=None if transcript is None else transcript.path,
        repo_name=memory_session.repo_name,
        worktree_label=memory_session.worktree_label,
        status=report.quality_status,
        reason=report.quality_reason,
        semantic_status=report.semantic_status,
        deterministic_status=report.deterministic_status,
        promotable=report.promotable,
        finding_counts=_finding_counts(deterministic_findings, semantic_findings),
        reference_defect_count=reference_defect_count,
        updated_at=report.updated_at,
        interpretation_job_id=snapshot.job_id,
        detail={
            "quality_report_id": report.id,
            "snapshot_id": snapshot.id,
            "snapshot_status": snapshot.status,
            "snapshot_job_id": snapshot.job_id,
            "analysis_run_id": snapshot.analysis_run_id,
            "quality_job_id": report.job_id,
            "quality_reason": report.quality_reason,
            "derivation_status": report.derivation_status,
            "deterministic_findings": deterministic_findings,
            "semantic_findings": semantic_findings,
            "claim_assessments": _as_list(report.claim_assessments_json),
            "missing_high_signal_items": _as_list(report.missing_high_signal_items_json),
            "assessment_metadata": assessment_metadata,
            "model_metadata": _as_dict(report.model_metadata_json),
            "prompt_version": report.prompt_version,
            "schema_version": report.schema_version,
            "created_at": report.created_at,
        },
    )


def _load_interpretation_failure_rows(
    db_session: Session,
    report_rows: list[QualityDashboardRow],
) -> list[QualityDashboardRow]:
    reported_session_ids = {row.session_id for row in report_rows if row.session_id is not None}
    reported_interpret_job_ids = {
        row.interpretation_job_id for row in report_rows if row.interpretation_job_id is not None
    }
    failed_jobs = db_session.scalars(
        select(Job)
        .where(Job.kind == JOB_KIND_INTERPRET_SESSION, Job.status == JOB_STATUS_FAILED)
        .order_by(Job.updated_at.desc()),
    ).all()
    pending_jobs = [
        job
        for job in failed_jobs
        if job.id not in reported_interpret_job_ids
        and _payload_session_id(job.payload_json) not in reported_session_ids
    ]
    sessions, transcripts = _load_failure_context(db_session, pending_jobs)
    return [_interpretation_failure_row(job, sessions=sessions, transcripts=transcripts) for job in pending_jobs]


def _load_failure_context(
    db_session: Session,
    jobs: list[Job],
) -> tuple[dict[str, MemorySession], dict[int, Transcript]]:
    session_ids = {session_id for job in jobs if (session_id := _payload_session_id(job.payload_json)) is not None}
    transcript_ids = {
        transcript_id for job in jobs if (transcript_id := _payload_transcript_id(job.payload_json)) is not None
    }

    session_query = select(MemorySession).where(MemorySession.session_id.in_(session_ids))
    sessions = {memory_session.session_id: memory_session for memory_session in db_session.scalars(session_query).all()}
    transcripts = {
        transcript.id: transcript
        for transcript in db_session.scalars(select(Transcript).where(Transcript.id.in_(transcript_ids))).all()
    }
    return sessions, transcripts


def _interpretation_failure_row(
    job: Job,
    *,
    sessions: dict[str, MemorySession],
    transcripts: dict[int, Transcript],
) -> QualityDashboardRow:
    payload = _as_dict(job.payload_json)
    session_id = _payload_session_id(payload)
    transcript_id = _payload_transcript_id(payload)
    memory_session = sessions.get(session_id) if session_id is not None else None
    transcript = transcripts.get(transcript_id) if transcript_id is not None else None
    return QualityDashboardRow(
        row_id=f"interpret-job:{job.id}",
        row_type="interpretation_failure",
        session_id=session_id,
        transcript_id=transcript_id,
        transcript_path=None if transcript is None else transcript.path,
        repo_name=None if memory_session is None else memory_session.repo_name,
        worktree_label=None if memory_session is None else memory_session.worktree_label,
        status="interpretation_failed",
        reason=job.last_error,
        semantic_status=None,
        deterministic_status=None,
        promotable=False,
        finding_counts=_empty_finding_counts(),
        reference_defect_count=0,
        updated_at=job.updated_at,
        interpretation_job_id=job.id,
        detail={
            "job_id": job.id,
            "job_kind": job.kind,
            "job_status": job.status,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
            "run_id": job.run_id,
            "exit_code": job.exit_code,
            "last_error": job.last_error,
            "payload": payload,
            "result": _as_dict(job.result_json),
            "created_at": job.created_at,
            "finished_at": job.finished_at,
        },
    )


def _dashboard_data(
    rows: list[QualityDashboardRow],
    *,
    transcript_count: int,
    quality_report_count: int,
) -> QualityDashboardData:
    quality_status_counts = Counter(row.status for row in rows if row.row_type == "quality_report")
    return QualityDashboardData(
        rows=rows,
        transcript_count=transcript_count,
        quality_report_count=quality_report_count,
        row_count=len(rows),
        quality_status_counts=dict(quality_status_counts),
        promotable_count=sum(1 for row in rows if row.promotable is True),
        non_promotable_count=sum(1 for row in rows if row.promotable is not True),
        failed_interpretation_count=sum(1 for row in rows if row.row_type == "interpretation_failure"),
        quality_reference_defect_report_count=sum(
            1 for row in rows if row.row_type == "quality_report" and row.reference_defect_count > 0
        ),
        quality_reference_defect_count=sum(
            row.reference_defect_count for row in rows if row.row_type == "quality_report"
        ),
    )


def _finding_counts(*finding_groups: list[Any]) -> dict[str, int]:
    counts = _empty_finding_counts()
    for findings in finding_groups:
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            severity = finding.get("severity")
            if severity in counts:
                counts[severity] += 1
    return counts


def _empty_finding_counts() -> dict[str, int]:
    return {"critical": 0, "warning": 0, "info": 0}


def _reference_defect_count(metadata: dict[str, Any]) -> int:
    value = metadata.get("quality_reference_defect_count")
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


def _payload_session_id(payload: Any) -> str | None:
    value = _as_dict(payload).get("session_id")
    return value if isinstance(value, str) and value else None


def _payload_transcript_id(payload: Any) -> int | None:
    value = _as_dict(payload).get("transcript_id")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _row_sort_key(row: QualityDashboardRow) -> tuple[str, str]:
    updated_at = "" if row.updated_at is None else row.updated_at.isoformat()
    return (updated_at, row.row_id)
