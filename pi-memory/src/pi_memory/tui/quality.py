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
QualityFilterMode = Literal["all", "healthy", "degraded", "gaps"]

QUALITY_LIMIT_STATUSES = {"assessment_failed", "failed", "not_assessed"}
TABLE_COLUMNS = (
    ("transcript", 28, "transcript"),
    ("session", 18, "session"),
    ("coverage", 18, "coverage"),
    ("confidence", 12, "confidence"),
    ("quality signals", 18, "signals"),
    ("limits", 18, "limits"),
    ("updated", 19, "updated"),
)
DISTRIBUTION_BAR_WIDTH = 12
MAX_DETAIL_FINDINGS = 2


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
    SUB_TITLE = "Memory quality observability"
    BINDINGS = [
        ("a", "show_all", "all"),
        ("h", "show_healthy", "healthy"),
        ("d", "show_degraded", "degraded"),
        ("f", "show_gaps", "gaps/limits"),
        ("p", "toggle_promotable", "promotable"),
        ("r", "reload", "reload"),
        ("q", "quit", "quit"),
    ]
    CSS = """
    #quality-screen {
        layout: vertical;
    }

    #quality-overview {
        height: 4;
        padding: 0 1;
    }

    #quality-distribution {
        height: 6;
        border: solid $primary;
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
        height: 10;
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
            yield Static("Loading memory quality overview...", id="quality-overview")
            yield Static("Loading assessment outcomes...", id="quality-distribution")
            yield Static(self._help_text(), id="quality-help")
            yield DataTable(id="quality-table")
            yield Static("Select an evidence row to show details.", id="quality-detail")
        yield Footer()

    def on_mount(self) -> None:
        """Load data and configure the table after widgets are mounted."""
        table = self.query_one("#quality-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        self._reload_data()

    def action_show_all(self) -> None:
        """Show all evidence rows."""
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

    def action_show_gaps(self) -> None:
        """Show coverage gaps and quality limits."""
        self._filter_mode = "gaps"
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
        self.query_one("#quality-overview", Static).update(self._overview_text())
        self.query_one("#quality-distribution", Static).update(self._distribution_text())
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
        if self._filter_mode == "gaps":
            return (
                row.row_type == "interpretation_failure"
                or row.status in QUALITY_LIMIT_STATUSES
                or row.reference_defect_count > 0
            )
        return True

    def _overview_text(self) -> str:
        if self.data is None:
            return "Loading memory quality overview..."
        return _dashboard_overview_text(self.data, self.db_url)

    def _distribution_text(self) -> str:
        if self.data is None:
            return "Loading assessment outcomes..."
        return _assessment_distribution_text(self.data)

    def _help_text(self) -> str:
        promotable = "on" if self._promotable_only else "off"
        return (
            "Evidence filters: a all | h healthy | d degraded | f coverage gaps/limits | "
            f"p promotable-only ({promotable}) | r reload | q quit | view: {self._filter_label()}"
        )

    def _filter_label(self) -> str:
        labels = {
            "all": "all evidence",
            "healthy": "healthy confidence",
            "degraded": "degraded reports",
            "gaps": "coverage gaps/limits",
        }
        return labels[self._filter_mode]

    def _table_cells(self, row: QualityDashboardRow) -> tuple[str, ...]:
        return (
            _transcript_label(row),
            _compact(row.session_id),
            _coverage_label(row),
            _confidence_label(row),
            _quality_signal_label(row),
            _quality_limit_label(row),
            _format_datetime(row.updated_at),
        )

    def _show_row_detail(self, row_id: str) -> None:
        row = self._rows_by_key.get(row_id)
        if row is None:
            return
        self.query_one("#quality-detail", Static).update(_detail_text(row))


def _dashboard_overview_text(data: QualityDashboardData, db_url: str) -> str:
    coverage_gaps = _coverage_gap_count(data)
    assessment_failures = _quality_assessment_failure_count(data)
    not_assessed = data.quality_status_counts.get("not_assessed", 0)
    return "\n".join(
        (
            "Memory quality overview",
            (
                f"Coverage {data.quality_report_count}/{data.transcript_count} "
                f"({_percentage_label(data.quality_report_count, data.transcript_count)}) | "
                f"Confidence {data.promotable_count}/{data.transcript_count} "
                f"({_percentage_label(data.promotable_count, data.transcript_count)})"
            ),
            (
                f"Outcomes {data.quality_status_counts.get('healthy', 0)} healthy | "
                f"{data.quality_status_counts.get('degraded', 0)} degraded | "
                f"{not_assessed} not assessed | {assessment_failures} assessment failed | "
                f"{coverage_gaps} no report"
            ),
            (
                f"Limits {data.quality_reference_defect_report_count} ref-defect reports / "
                f"{data.quality_reference_defect_count} refs omitted | DB {_truncate(db_url, 84)}"
            ),
        ),
    )


def _assessment_distribution_text(data: QualityDashboardData) -> str:
    total = max(data.transcript_count, data.row_count, 1)
    assessment_failures = _quality_assessment_failure_count(data)
    coverage_gaps = _coverage_gap_count(data)
    rows = [
        (
            "healthy",
            data.quality_status_counts.get("healthy", 0),
            "passed semantic quality",
        ),
        (
            "degraded",
            data.quality_status_counts.get("degraded", 0),
            "quality limits captured; may still be promotable",
        ),
        (
            "not assessed",
            data.quality_status_counts.get("not_assessed", 0),
            "report exists without semantic assessment",
        ),
        (
            "assessment failed",
            assessment_failures,
            "quality assessment did not complete cleanly",
        ),
        (
            "no quality report",
            coverage_gaps,
            f"{data.failed_interpretation_count} known interpretation gaps",
        ),
    ]
    lines = ["Transcript assessment outcomes"]
    lines.extend(_distribution_line(label, count, total, note) for label, count, note in rows)
    return "\n".join(lines)


def _distribution_line(label: str, count: int, total: int, note: str) -> str:
    return f"{label:<17} {_distribution_bar(count, total)} {count:>4}  {_truncate(note, 34)}"


def _distribution_bar(count: int, total: int) -> str:
    if total <= 0 or count <= 0:
        filled_width = 0
    else:
        filled_width = round((count / total) * DISTRIBUTION_BAR_WIDTH)
        filled_width = max(filled_width, 1)
    filled_width = min(filled_width, DISTRIBUTION_BAR_WIDTH)
    return "█" * filled_width + "░" * (DISTRIBUTION_BAR_WIDTH - filled_width)


def _coverage_gap_count(data: QualityDashboardData) -> int:
    return max(data.transcript_count - data.quality_report_count, 0)


def _quality_assessment_failure_count(data: QualityDashboardData) -> int:
    return data.quality_status_counts.get("assessment_failed", 0) + data.quality_status_counts.get("failed", 0)


def _percentage_label(value: int, total: int) -> str:
    if total <= 0:
        return "n/a"
    return f"{(value / total) * 100:.1f}%"


def _row_type_label(row: QualityDashboardRow) -> str:
    if row.row_type == "quality_report":
        return "quality report"
    return "coverage gap"


def _coverage_label(row: QualityDashboardRow) -> str:
    if row.row_type == "interpretation_failure":
        return "no quality report"
    return _status_label(row.status)


def _quality_signal_label(row: QualityDashboardRow) -> str:
    if row.row_type == "interpretation_failure":
        return "interpretation gap"
    detail = row.detail
    claim_count = len(_as_list(detail.get("claim_assessments")))
    missing_count = len(_as_list(detail.get("missing_high_signal_items")))
    return f"claims {claim_count} | gaps {missing_count}"


def _quality_limit_label(row: QualityDashboardRow) -> str:
    if row.row_type == "interpretation_failure":
        return "no assessment"
    limits: list[str] = []
    if row.reference_defect_count > 0:
        limits.append(f"refs {row.reference_defect_count}")
    finding_total = sum(row.finding_counts.values())
    if finding_total > 0:
        limits.append(f"findings {finding_total}")
    if row.status in QUALITY_LIMIT_STATUSES:
        limits.append(_status_label(row.status))
    return " | ".join(limits) if limits else "none"


def _status_label(status: str) -> str:
    labels = {
        "assessment_failed": "assessment failed",
        "interpretation_failed": "interpretation gap",
        "not_assessed": "not assessed",
    }
    return labels.get(status, status.replace("_", " "))


def _confidence_label(row: QualityDashboardRow) -> str:
    if row.promotable is True:
        return "promotable"
    if row.row_type == "interpretation_failure":
        return "no report"
    if row.promotable is False:
        return "limited"
    return "n/a"


def _detail_text(row: QualityDashboardRow) -> str:
    lines = [
        f"Transcript {_transcript_label(row)}",
        f"path={_detail_path_label(row.transcript_path)}",
        (
            f"session={_compact(row.session_id)} | repo={_display_compact(row.repo_name)} | "
            f"worktree={_display_compact(row.worktree_label)}"
        ),
        (
            f"coverage={_coverage_label(row)} | confidence={_confidence_label(row)} | "
            f"updated={_compact_datetime(row.updated_at)}"
        ),
    ]
    if row.row_type == "quality_report":
        lines.extend(_quality_detail_lines(row))
    else:
        lines.extend(_coverage_gap_detail_lines(row))
    return "\n".join(lines)


def _quality_detail_lines(row: QualityDashboardRow) -> list[str]:
    detail = row.detail
    claim_count = len(_as_list(detail.get("claim_assessments")))
    missing_count = len(_as_list(detail.get("missing_high_signal_items")))
    deterministic_findings = _as_list(detail.get("deterministic_findings"))
    semantic_findings = _as_list(detail.get("semantic_findings"))
    lines = [
        (
            f"checks: det={_display_compact(row.deterministic_status)} | "
            f"semantic={_display_compact(row.semantic_status)} | "
            f"derivation={_display_compact(detail.get('derivation_status'))}"
        ),
        (
            f"evidence: claims={claim_count} | gaps={missing_count} | "
            f"findings {_finding_counts_label(row.finding_counts)} | ref limits={row.reference_defect_count}"
        ),
        f"quality note={_display_detail(row.reason)}",
    ]
    lines.extend(_compact_finding_lines("deterministic", deterministic_findings))
    lines.extend(_compact_finding_lines("semantic", semantic_findings))
    return lines


def _coverage_gap_detail_lines(row: QualityDashboardRow) -> list[str]:
    detail = row.detail
    return [
        "quality report: none for this transcript",
        "gap: no quality-assessable memory snapshot was produced.",
        f"gap detail={_display_detail(detail.get('last_error'))}",
    ]


def _compact_finding_lines(label: str, findings: list[Any]) -> list[str]:
    if not findings:
        return []
    shown = [_compact_finding_label(finding) for finding in findings[:MAX_DETAIL_FINDINGS]]
    if len(findings) > MAX_DETAIL_FINDINGS:
        shown.append(f"{len(findings) - MAX_DETAIL_FINDINGS} more")
    return [f"{label} findings: " + " | ".join(shown)]


def _compact_finding_label(finding: Any) -> str:
    if not isinstance(finding, dict):
        return _truncate(str(finding), 64)
    severity = _display_compact(finding.get("severity"))
    code = _display_compact(finding.get("code"))
    message = _display_detail(finding.get("message") or finding.get("description"), limit=52)
    return _truncate(f"{severity} {code}: {message}", 72)


def _format_scalar(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, datetime):
        return _format_datetime(value)
    if isinstance(value, str | int | float | bool):
        return str(value)
    return json.dumps(value, default=str, sort_keys=True)


def _transcript_label(row: QualityDashboardRow) -> str:
    if row.transcript_path:
        path_label = row.transcript_path.rsplit("/", maxsplit=1)[-1]
        if row.transcript_id is not None:
            return _truncate(f"{row.transcript_id} {path_label}", 32)
        return _truncate(path_label, 32)
    if row.transcript_id is not None:
        return str(row.transcript_id)
    return "n/a"


def _finding_counts_label(counts: dict[str, int]) -> str:
    return f"c:{counts.get('critical', 0)} w:{counts.get('warning', 0)} i:{counts.get('info', 0)}"


def _display_compact(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    return _truncate(_format_scalar(value), 24)


def _display_detail(value: Any, *, limit: int = 72) -> str:
    if value is None or value == "":
        return "n/a"
    return _truncate(_format_scalar(value), limit)


def _detail_path_label(path: str | None) -> str:
    if not path:
        return "n/a"
    return _truncate(path, 68)


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


def _compact_datetime(value: datetime | None) -> str:
    if value is None:
        return "n/a"
    return value.isoformat(timespec="minutes")


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
