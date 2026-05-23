"""Quality report Textual application seam and read-only dashboard data loader."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, Footer, Header, Static

from pi_memory.db.constants import (
    ACTIVITY_KIND_TOOL_PAIR,
    JOB_KIND_INTERPRET_SESSION,
    JOB_STATUS_FAILED,
)
from pi_memory.db.database import Database
from pi_memory.db.models import (
    ActivityUnit,
    Episode,
    EpisodeInterpretationSnapshot,
    Job,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    Transcript,
    TranscriptEntry,
)

QualityDashboardRowType = Literal["quality_report", "interpretation_failure"]
QualityFilterMode = Literal["all", "healthy", "degraded", "gaps"]

QUALITY_LIMIT_STATUSES = {"assessment_failed", "failed", "not_assessed"}
TABLE_COLUMNS = (
    ("transcript", 28, "transcript"),
    ("session", 18, "session"),
    ("coverage", 18, "coverage"),
    ("confidence", 12, "confidence"),
    ("structure", 20, "structure"),
    ("limits", 18, "limits"),
    ("updated", 19, "updated"),
)
DISTRIBUTION_BAR_WIDTH = 12


@dataclass(frozen=True)
class TranscriptSessionMetadata:
    """Read-only transcript and session context for a dashboard row."""

    entry_count: int = 0
    activity_count: int = 0
    episode_count: int = 0
    tool_activity_count: int = 0
    session_transcript_count: int = 0
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    file_size: int | None = None
    cursor_offset: int | None = None
    parent_transcript_path: str | None = None


@dataclass(frozen=True)
class QualityDashboardRow:
    """A normalized row for the quality dashboard table."""

    row_id: str
    row_type: QualityDashboardRowType
    session_id: str | None
    transcript_id: int | None
    transcript_path: str | None
    cwd: str | None
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
    transcript_metadata: TranscriptSessionMetadata = field(default_factory=TranscriptSessionMetadata)
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
            rows = _with_transcript_metadata(db_session, [*report_rows, *failure_rows])
    finally:
        quality_database.close_if_open()

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
                or _has_episode_coverage_limit(row)
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
            _structure_label(row.transcript_metadata),
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


def _structure_label(metadata: TranscriptSessionMetadata) -> str:
    return f"ent {metadata.entry_count} | act {metadata.activity_count} | ep {metadata.episode_count}"


def _structure_detail_label(metadata: TranscriptSessionMetadata) -> str:
    return (
        f"ent={metadata.entry_count} act={metadata.activity_count} ep={metadata.episode_count} "
        f"tools={metadata.tool_activity_count} session-tx={metadata.session_transcript_count}"
    )


def _timeline_detail_label(metadata: TranscriptSessionMetadata) -> str:
    return (
        f"{_time_span_label(metadata)} | file={_byte_count_label(metadata.file_size)} "
        f"cursor={_byte_count_label(metadata.cursor_offset)} parent={_parent_label(metadata)}"
    )


def _quality_limit_label(row: QualityDashboardRow) -> str:
    if row.row_type == "interpretation_failure":
        return _episode_coverage_limit_label(row) or "no assessment"
    limits: list[str] = []
    episode_limit = _episode_coverage_limit_label(row)
    if episode_limit:
        limits.append(episode_limit)
    if row.reference_defect_count > 0:
        limits.append(f"refs {row.reference_defect_count}")
    finding_total = sum(row.finding_counts.values())
    if finding_total > 0:
        limits.append(f"findings {finding_total}")
    if row.status in QUALITY_LIMIT_STATUSES:
        limits.append(_status_label(row.status))
    return " | ".join(limits) if limits else "none"


def _episode_coverage_limit_label(row: QualityDashboardRow) -> str | None:
    coverage = _episode_interpretation_coverage(row)
    status = coverage.get("coverage_status")
    if status == "partial":
        failed = coverage.get("failed_episode_count")
        return f"ep partial {failed}" if isinstance(failed, int) and failed > 0 else "ep partial"
    if row.row_type == "interpretation_failure" and status == "failed":
        failed = coverage.get("failed_episode_count")
        return f"ep failed {failed}" if isinstance(failed, int) and failed > 0 else "ep failed"
    return None


def _has_episode_coverage_limit(row: QualityDashboardRow) -> bool:
    return _episode_coverage_limit_label(row) is not None


def _episode_interpretation_coverage(row: QualityDashboardRow) -> dict[str, Any]:
    return _as_dict(row.detail.get("episode_interpretation"))


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
    metadata = row.transcript_metadata
    lines = [
        f"Transcript {_transcript_label(row)}",
        f"path={_detail_path_label(row.transcript_path)}",
        (
            f"session={_compact(row.session_id)} | cwd={_display_compact(row.cwd)} | "
            f"worktree={_display_compact(row.worktree_label)}"
        ),
        (
            f"coverage={_coverage_label(row)} | confidence={_confidence_label(row)} | "
            f"updated={_compact_datetime(row.updated_at)}"
        ),
        f"structure: {_structure_detail_label(metadata)}",
        f"timeline: {_timeline_detail_label(metadata)}",
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
    return [
        _episode_coverage_detail_line(row),
        (
            f"checks: det={_display_compact(row.deterministic_status)} | "
            f"semantic={_display_compact(row.semantic_status)} | "
            f"derivation={_display_compact(detail.get('derivation_status'))}"
        ),
        (
            f"memory: claims={claim_count} gaps={missing_count} f={_finding_counts_label(row.finding_counts)} "
            f"refs={row.reference_defect_count} note={_display_detail(row.reason, limit=18)}"
        ),
    ]


def _coverage_gap_detail_lines(row: QualityDashboardRow) -> list[str]:
    detail = row.detail
    return [
        "quality report: none for this transcript",
        _episode_coverage_detail_line(row),
        f"gap detail={_display_detail(detail.get('last_error'))}",
    ]


def _episode_coverage_detail_line(row: QualityDashboardRow) -> str:
    coverage = _episode_interpretation_coverage(row)
    if not coverage:
        return "episodes: n/a"
    return (
        f"episodes: coverage={_display_compact(coverage.get('coverage_status'))} "
        f"completed={_display_compact(coverage.get('completed_episode_count'))}/"
        f"{_display_compact(coverage.get('claim_source_episode_count'))} "
        f"failed={_display_compact(coverage.get('failed_episode_count'))} "
        f"skipped={_display_compact(coverage.get('skipped_episode_count'))}"
    )


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


def _time_span_label(metadata: TranscriptSessionMetadata) -> str:
    if metadata.first_timestamp is None and metadata.last_timestamp is None:
        return "n/a"
    if metadata.first_timestamp is None or metadata.last_timestamp is None:
        return _compact_datetime(metadata.first_timestamp or metadata.last_timestamp)
    if metadata.first_timestamp.date() == metadata.last_timestamp.date():
        return f"{metadata.first_timestamp:%Y-%m-%d %H:%M}→{metadata.last_timestamp:%H:%M}"
    return f"{_compact_datetime(metadata.first_timestamp)}→{_compact_datetime(metadata.last_timestamp)}"


def _byte_count_label(value: int | None) -> str:
    if value is None:
        return "n/a"
    if value < 1024:
        return f"{value}B"
    if value < 1024 * 1024:
        return f"{value / 1024:.0f}K"
    return f"{value / (1024 * 1024):.1f}M"


def _parent_label(metadata: TranscriptSessionMetadata) -> str:
    if not metadata.parent_transcript_path:
        return "none"
    return _truncate(metadata.parent_transcript_path.rsplit("/", maxsplit=1)[-1], 18)


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


def _with_transcript_metadata(
    db_session: Session,
    rows: list[QualityDashboardRow],
) -> list[QualityDashboardRow]:
    metadata_by_transcript_id = _load_metadata_by_transcript_id(db_session, rows)
    return [
        replace(
            row,
            transcript_metadata=metadata_by_transcript_id.get(row.transcript_id, TranscriptSessionMetadata()),
        )
        for row in rows
    ]


def _load_metadata_by_transcript_id(
    db_session: Session,
    rows: list[QualityDashboardRow],
) -> dict[int, TranscriptSessionMetadata]:
    transcript_ids = {row.transcript_id for row in rows if row.transcript_id is not None}
    if not transcript_ids:
        return {}

    transcripts = _load_transcripts_by_id(db_session, transcript_ids)
    entry_stats = _load_entry_stats_by_transcript_id(db_session, transcript_ids)
    activity_stats = _load_activity_stats_by_transcript_id(db_session, transcript_ids)
    episode_counts = _load_episode_counts_by_transcript_id(db_session, transcript_ids)
    session_counts = _load_session_transcript_counts(db_session, transcripts.values())

    return {
        transcript_id: _transcript_metadata(
            transcript=transcript,
            entry_stats=entry_stats.get(transcript_id, (0, None, None)),
            activity_stats=activity_stats.get(transcript_id, (0, 0)),
            episode_count=episode_counts.get(transcript_id, 0),
            session_transcript_count=session_counts.get(transcript.session_id, 0),
        )
        for transcript_id, transcript in transcripts.items()
    }


def _load_transcripts_by_id(db_session: Session, transcript_ids: set[int]) -> dict[int, Transcript]:
    return {
        transcript.id: transcript
        for transcript in db_session.scalars(select(Transcript).where(Transcript.id.in_(transcript_ids))).all()
    }


def _load_entry_stats_by_transcript_id(
    db_session: Session,
    transcript_ids: set[int],
) -> dict[int, tuple[int, datetime | None, datetime | None]]:
    rows = db_session.execute(
        select(
            TranscriptEntry.transcript_id,
            func.count(TranscriptEntry.id),
            func.min(TranscriptEntry.timestamp),
            func.max(TranscriptEntry.timestamp),
        )
        .where(TranscriptEntry.transcript_id.in_(transcript_ids))
        .group_by(TranscriptEntry.transcript_id),
    ).all()
    return {
        transcript_id: (int(entry_count), first_timestamp, last_timestamp)
        for transcript_id, entry_count, first_timestamp, last_timestamp in rows
    }


def _load_activity_stats_by_transcript_id(
    db_session: Session,
    transcript_ids: set[int],
) -> dict[int, tuple[int, int]]:
    rows = db_session.execute(
        select(
            ActivityUnit.transcript_id,
            func.count(ActivityUnit.id),
            func.sum(case((ActivityUnit.kind == ACTIVITY_KIND_TOOL_PAIR, 1), else_=0)),
        )
        .where(ActivityUnit.transcript_id.in_(transcript_ids))
        .group_by(ActivityUnit.transcript_id),
    ).all()
    stats: dict[int, tuple[int, int]] = {}
    for transcript_id, activity_count, tool_count in rows:
        stats[transcript_id] = (int(activity_count), int(tool_count or 0))
    return stats


def _load_episode_counts_by_transcript_id(db_session: Session, transcript_ids: set[int]) -> dict[int, int]:
    rows = db_session.execute(
        select(Episode.transcript_id, func.count(Episode.id))
        .where(Episode.transcript_id.in_(transcript_ids))
        .group_by(Episode.transcript_id),
    ).all()
    return {transcript_id: int(episode_count) for transcript_id, episode_count in rows}


def _load_session_transcript_counts(
    db_session: Session,
    transcripts: Iterable[Transcript],
) -> dict[int, int]:
    session_database_ids = {transcript.session_id for transcript in transcripts}
    if not session_database_ids:
        return {}
    rows = db_session.execute(
        select(Transcript.session_id, func.count(Transcript.id))
        .where(Transcript.session_id.in_(session_database_ids))
        .group_by(Transcript.session_id),
    ).all()
    return {session_id: int(transcript_count) for session_id, transcript_count in rows}


def _transcript_metadata(
    *,
    transcript: Transcript,
    entry_stats: tuple[int, datetime | None, datetime | None],
    activity_stats: tuple[int, int],
    episode_count: int,
    session_transcript_count: int,
) -> TranscriptSessionMetadata:
    entry_count, first_timestamp, last_timestamp = entry_stats
    activity_count, tool_activity_count = activity_stats
    return TranscriptSessionMetadata(
        entry_count=entry_count,
        activity_count=activity_count,
        episode_count=episode_count,
        tool_activity_count=tool_activity_count,
        session_transcript_count=session_transcript_count,
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        file_size=transcript.file_size,
        cursor_offset=transcript.cursor_offset,
        parent_transcript_path=transcript.parent_transcript_path,
    )


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
    episode_interpretation = _snapshot_episode_interpretation_coverage(snapshot)
    return QualityDashboardRow(
        row_id=f"quality-report:{report.id}",
        row_type="quality_report",
        session_id=memory_session.session_id,
        transcript_id=snapshot.transcript_id,
        transcript_path=None if transcript is None else transcript.path,
        cwd=memory_session.cwd,
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
            "episode_interpretation": episode_interpretation,
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


def _snapshot_episode_interpretation_coverage(snapshot: SessionInterpretationSnapshot) -> dict[str, Any]:
    interpretation = snapshot.interpretation_json if isinstance(snapshot.interpretation_json, dict) else {}
    return _as_dict(interpretation.get("aggregation"))


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
    episode_summaries = _load_failure_episode_summaries(db_session, pending_jobs)
    return [
        _interpretation_failure_row(
            job,
            sessions=sessions,
            transcripts=transcripts,
            episode_summaries=episode_summaries,
        )
        for job in pending_jobs
    ]


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


def _load_failure_episode_summaries(
    db_session: Session,
    jobs: list[Job],
) -> dict[int, dict[str, Any]]:
    job_ids = {job.id for job in jobs}
    if not job_ids:
        return {}
    rows = db_session.execute(
        select(
            EpisodeInterpretationSnapshot.job_id,
            EpisodeInterpretationSnapshot.status,
            func.count(EpisodeInterpretationSnapshot.id),
            func.sum(EpisodeInterpretationSnapshot.claim_source_activity_count),
        )
        .where(EpisodeInterpretationSnapshot.job_id.in_(job_ids))
        .group_by(EpisodeInterpretationSnapshot.job_id, EpisodeInterpretationSnapshot.status),
    ).all()
    summaries: dict[int, dict[str, Any]] = {}
    for job_id, status, count, claim_source_count in rows:
        if job_id is None:
            continue
        summary = summaries.setdefault(
            job_id,
            {
                "coverage_status": "failed",
                "completed_episode_count": 0,
                "skipped_episode_count": 0,
                "failed_episode_count": 0,
                "claim_source_episode_count": 0,
                "total_claim_source_activity_count": 0,
            },
        )
        _apply_episode_summary_count(summary, status, int(count), int(claim_source_count or 0))
    return summaries


def _apply_episode_summary_count(summary: dict[str, Any], status: str, count: int, claim_source_count: int) -> None:
    if status == "completed":
        summary["completed_episode_count"] += count
        summary["claim_source_episode_count"] += count
    elif status == "skipped_no_claim_sources":
        summary["skipped_episode_count"] += count
    elif status == "failed":
        summary["failed_episode_count"] += count
        summary["claim_source_episode_count"] += count
    summary["total_claim_source_activity_count"] += claim_source_count


def _interpretation_failure_row(
    job: Job,
    *,
    sessions: dict[str, MemorySession],
    transcripts: dict[int, Transcript],
    episode_summaries: dict[int, dict[str, Any]],
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
        cwd=None if memory_session is None else memory_session.cwd,
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
            "episode_interpretation": episode_summaries.get(job.id, {}),
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
