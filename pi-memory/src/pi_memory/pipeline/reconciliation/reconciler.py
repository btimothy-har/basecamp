"""Minimal repair-oriented reconciliation for the Pi memory pipeline."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pi_memory.constants import (
    ACTIVITY_KIND_TOOL_PAIR,
    ACTIVITY_TEXT_STATUS_PENDING,
    ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    ANALYSIS_STATUS_COMPLETED,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_CLAIMED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    SESSION_INTERPRETATION_STATUS_BLOCKED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
    SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
)
from pi_memory.db.database import Database, database
from pi_memory.db.models import (
    ActivityUnit,
    AnalysisRun,
    Job,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
)
from pi_memory.infra.job_queue import JobStore
from pi_memory.pipeline.reconciliation.contracts import (
    EnqueueSpec,
    GateDecision,
    GateTarget,
    ReconciliationReport,
    ReconciliationRunOptions,
)
from pi_memory.pipeline.stages.assess_interpretation_quality.enqueue import (
    assess_interpretation_quality_idempotency_key,
    assess_interpretation_quality_job_spec,
)
from pi_memory.pipeline.stages.interpret_session.enqueue import (
    interpret_session_idempotency_key,
    interpret_session_job_spec,
)
from pi_memory.pipeline.stages.project_memory_records.enqueue import (
    project_memory_records_idempotency_key,
    project_memory_records_job_spec,
)
from pi_memory.pipeline.stages.promote_durable_memory.enqueue import (
    promote_durable_memory_idempotency_key,
    promote_durable_memory_job_spec,
)
from pi_memory.pipeline.stages.summarize_tool_activities.enqueue import (
    summarize_tool_activities_idempotency_key,
    summarize_tool_activities_job_spec_from_fields,
)

GATE_ANALYSIS_TO_SUMMARIZE = "analysis_to_summarize"
GATE_SUMMARIZE_TO_INTERPRET = "summarize_to_interpret"
GATE_SNAPSHOT_TO_QUALITY = "snapshot_to_quality"
GATE_QUALITY_TO_PROJECT = "quality_to_project"
GATE_QUALITY_TO_PROMOTE = "quality_to_promote"


class Reconciler:
    """Reconcile missing child jobs between stable pipeline stages."""

    def __init__(self, database: Database = database) -> None:
        self._database = database
        self._store = JobStore(database=database)

    def run_once(self, options: ReconciliationRunOptions | None = None) -> ReconciliationReport:
        """Run one reconciliation sweep and optionally enqueue missing jobs."""
        current_options = ReconciliationRunOptions() if options is None else options
        decisions: list[GateDecision] = []

        self._database.initialize()
        with self._database.session() as session:
            latest_analysis_runs = self._latest_completed_analysis_runs(session)

            if self._should_run_gate(current_options, GATE_ANALYSIS_TO_SUMMARIZE):
                decisions.extend(self._gate_analysis_to_summarize(session, latest_analysis_runs))

            if self._should_run_gate(current_options, GATE_SUMMARIZE_TO_INTERPRET):
                decisions.extend(self._gate_summarize_to_interpret(session, latest_analysis_runs))

            if self._should_run_gate(current_options, GATE_SNAPSHOT_TO_QUALITY):
                decisions.extend(self._gate_snapshot_to_quality(session))

            if self._should_run_gate(current_options, GATE_QUALITY_TO_PROJECT):
                decisions.extend(self._gate_quality_to_project(session))

            if self._should_run_gate(current_options, GATE_QUALITY_TO_PROMOTE):
                decisions.extend(self._gate_quality_to_promote(session))

        enqueued_job_ids: list[int] = []
        if current_options.enqueue_missing:
            enqueued_job_ids = self._enqueue_missing_decisions(
                decisions,
                max_enqueues=current_options.max_enqueues,
            )

        return ReconciliationReport(
            as_of=current_options.as_of or datetime.now(UTC),
            decisions=tuple(decisions),
            enqueued_job_ids=tuple(enqueued_job_ids),
        )

    def _should_run_gate(self, options: ReconciliationRunOptions, gate_name: str) -> bool:
        return options.gate_names is None or gate_name in options.gate_names

    def _enqueue_missing_decisions(
        self,
        decisions: list[GateDecision],
        *,
        max_enqueues: int | None,
    ) -> list[int]:
        enqueued_ids: list[int] = []
        for decision in decisions:
            if not decision.can_enqueue:
                continue
            if max_enqueues is not None and len(enqueued_ids) >= max_enqueues:
                break
            if decision.enqueue_spec is None:
                continue
            job = self._store.enqueue(**decision.enqueue_spec.model_dump())
            enqueued_ids.append(job.id)
        return enqueued_ids

    def _latest_completed_analysis_runs(self, session: Session) -> tuple[AnalysisRun, ...]:
        latest_analysis_run_ids = (
            select(func.max(AnalysisRun.id))
            .where(
                AnalysisRun.analysis_kind == ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
                AnalysisRun.status == ANALYSIS_STATUS_COMPLETED,
            )
            .group_by(AnalysisRun.transcript_id)
        )
        rows = session.scalars(
            select(AnalysisRun)
            .where(AnalysisRun.id.in_(latest_analysis_run_ids))
            .order_by(AnalysisRun.id.asc()),
        ).all()
        return tuple(rows)

    def _gate_analysis_to_summarize(
        self,
        session: Session,
        analysis_runs: tuple[AnalysisRun, ...],
    ) -> list[GateDecision]:
        decisions: list[GateDecision] = []
        for analysis_run in analysis_runs:
            target = GateTarget(
                gate=GATE_ANALYSIS_TO_SUMMARIZE,
                kind="analysis_run",
                identity={
                    "analysis_run_id": analysis_run.id,
                    "transcript_id": analysis_run.transcript_id,
                },
            )

            if analysis_run.job_id is None:
                decisions.append(
                    GateDecision(
                        target=target,
                        status="blocked",
                        reason="analysis run has no process job id",
                    ),
                )
                continue

            spec = summarize_tool_activities_job_spec_from_fields(
                transcript_id=analysis_run.transcript_id,
                session_id=analysis_run.session.session_id,
                analysis_run_id=analysis_run.id,
                process_job_id=analysis_run.job_id,
                analyzed_through_entry_id=analysis_run.analyzed_through_entry_id,
                analyzed_through_byte_offset=analysis_run.analyzed_through_byte_offset,
                activity_count=analysis_run.activity_count,
                episode_count=analysis_run.episode_count,
                manifest_count=analysis_run.manifest_count,
                idempotency_key=summarize_tool_activities_idempotency_key(analysis_run.job_id),
            )
            decision_status, existing_job_id, existing_job_ids = self._inspect_child_job_status(session, spec)
            if decision_status == "missing":
                decisions.append(
                    GateDecision(
                        target=target,
                        status="missing",
                        reason="analysis-to-summarize child job is missing",
                        enqueue_spec=spec,
                        details={
                            "analysis_run_id": analysis_run.id,
                            "analysis_kind": analysis_run.analysis_kind,
                        },
                    ),
                )
                continue

            decisions.append(
                GateDecision(
                    target=target,
                    status=decision_status,
                    reason="analysis-to-summarize child job status observed",
                    existing_job_id=existing_job_id,
                    existing_job_ids=existing_job_ids,
                    details={
                        "analysis_run_id": analysis_run.id,
                        "analysis_kind": analysis_run.analysis_kind,
                    },
                ),
            )

        return decisions

    def _gate_summarize_to_interpret(
        self,
        session: Session,
        analysis_runs: tuple[AnalysisRun, ...],
    ) -> list[GateDecision]:
        decisions: list[GateDecision] = []
        for analysis_run in analysis_runs:
            target = GateTarget(
                gate=GATE_SUMMARIZE_TO_INTERPRET,
                kind="analysis_run",
                identity={
                    "analysis_run_id": analysis_run.id,
                    "transcript_id": analysis_run.transcript_id,
                },
            )

            summarize_job_status, summarize_job_id, summarize_job_existing_ids = self._analysis_summarize_child(
                session,
                analysis_run,
            )
            if summarize_job_status == "missing":
                decisions.append(
                    GateDecision(
                        target=target,
                        status="blocked",
                        reason="summarize job is required before interpret job",
                    ),
                )
                continue
            if summarize_job_status == "in_flight":
                decisions.append(
                    GateDecision(
                        target=target,
                        status="in_flight",
                        reason="summarize job is still running",
                        existing_job_id=summarize_job_id,
                        existing_job_ids=summarize_job_existing_ids,
                    ),
                )
                continue
            if summarize_job_status == "blocked":
                decisions.append(
                    GateDecision(
                        target=target,
                        status="blocked",
                        reason="summarize child job was cancelled",
                        existing_job_id=summarize_job_id,
                        existing_job_ids=summarize_job_existing_ids,
                    ),
                )
                continue

            if self._has_pending_tool_pair_summaries(session, analysis_run):
                decisions.append(
                    GateDecision(
                        target=target,
                        status="failed" if summarize_job_status == "failed" else "blocked",
                        reason="tool-pair summaries are still pending",
                        existing_job_id=summarize_job_id,
                        existing_job_ids=summarize_job_existing_ids,
                    ),
                )
                continue

            if summarize_job_id is None:
                # Guard to keep typing clear; this path already checked non-missing statuses.
                decisions.append(
                    GateDecision(
                        target=target,
                        status="blocked",
                        reason="summarize job id is missing",
                    ),
                )
                continue

            interpret_job_spec = self._build_interpret_session_job_spec(
                analysis_run,
                summarize_job_id,
            )
            decision_status, existing_job_id, existing_job_ids = self._inspect_child_job_status(
                session,
                interpret_job_spec,
            )
            if decision_status == "missing":
                decisions.append(
                    GateDecision(
                        target=target,
                        status="missing",
                        reason="summarize-to-interpret child job is missing",
                        enqueue_spec=interpret_job_spec,
                        details={
                            "analysis_run_id": analysis_run.id,
                            "summarize_job_id": summarize_job_id,
                        },
                    ),
                )
                continue

            decisions.append(
                GateDecision(
                    target=target,
                    status=decision_status,
                    reason="summarize-to-interpret child job status observed",
                    existing_job_id=existing_job_id,
                    existing_job_ids=existing_job_ids,
                    details={
                        "analysis_run_id": analysis_run.id,
                        "summarize_job_id": summarize_job_id,
                    },
                ),
            )

        return decisions

    def _analysis_summarize_child(
        self,
        session: Session,
        analysis_run: AnalysisRun,
    ) -> tuple[str, int | None, tuple[int, ...] | None]:
        if analysis_run.job_id is None:
            return "blocked", None, None

        summarize_spec = summarize_tool_activities_job_spec_from_fields(
            transcript_id=analysis_run.transcript_id,
            session_id=analysis_run.session.session_id,
            analysis_run_id=analysis_run.id,
            process_job_id=analysis_run.job_id,
            analyzed_through_entry_id=analysis_run.analyzed_through_entry_id,
            analyzed_through_byte_offset=analysis_run.analyzed_through_byte_offset,
            activity_count=analysis_run.activity_count,
            episode_count=analysis_run.episode_count,
            manifest_count=analysis_run.manifest_count,
            idempotency_key=summarize_tool_activities_idempotency_key(analysis_run.job_id),
        )
        status, existing_job_id, existing_job_ids = self._inspect_child_job_status(session, summarize_spec)
        if status == "missing":
            return "missing", None, None
        return status, existing_job_id, existing_job_ids

    def _build_interpret_session_job_spec(self, analysis_run: AnalysisRun, summarize_job_id: int) -> EnqueueSpec:
        return interpret_session_job_spec(
            transcript_id=analysis_run.transcript_id,
            session_id=analysis_run.session.session_id,
            analysis_run_id=analysis_run.id,
            process_job_id=analysis_run.job_id,
            analyzed_through_entry_id=analysis_run.analyzed_through_entry_id,
            analyzed_through_byte_offset=analysis_run.analyzed_through_byte_offset,
            activity_count=analysis_run.activity_count,
            episode_count=analysis_run.episode_count,
            manifest_count=analysis_run.manifest_count,
            idempotency_key=interpret_session_idempotency_key(summarize_job_id),
        )

    def _has_pending_tool_pair_summaries(self, session: Session, analysis_run: AnalysisRun) -> bool:
        pending_count = session.scalar(
            select(func.count(ActivityUnit.id)).where(
                ActivityUnit.analysis_run_id == analysis_run.id,
                ActivityUnit.kind == ACTIVITY_KIND_TOOL_PAIR,
                ActivityUnit.activity_text_status == ACTIVITY_TEXT_STATUS_PENDING,
            ),
        )
        return bool(pending_count and pending_count > 0)

    def _gate_snapshot_to_quality(self, session: Session) -> list[GateDecision]:
        snapshots = tuple(
            session.scalars(
                select(SessionInterpretationSnapshot).where(
                    SessionInterpretationSnapshot.status.in_(
                        (
                            SESSION_INTERPRETATION_STATUS_COMPLETED,
                            SESSION_INTERPRETATION_STATUS_BLOCKED,
                            SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
                        ),
                    ),
                ),
            ).all(),
        )
        decisions: list[GateDecision] = []
        for snapshot in snapshots:
            target = GateTarget(
                gate=GATE_SNAPSHOT_TO_QUALITY,
                kind="session_interpretation_snapshot",
                identity={"snapshot_id": snapshot.id},
            )
            spec = assess_interpretation_quality_job_spec(
                snapshot_id=snapshot.id,
                session_id=snapshot.session.session_id,
                interpretation_job_id=snapshot.job_id,
                idempotency_key=assess_interpretation_quality_idempotency_key(snapshot.id),
            )
            decision_status, existing_job_id, existing_job_ids = self._inspect_child_job_status(session, spec)
            if decision_status == "missing":
                decisions.append(
                    GateDecision(
                        target=target,
                        status="missing",
                        reason="snapshot-to-quality child job is missing",
                        enqueue_spec=spec,
                        details={
                            "snapshot_id": snapshot.id,
                            "snapshot_status": snapshot.status,
                        },
                    ),
                )
                continue

            decisions.append(
                GateDecision(
                    target=target,
                    status=decision_status,
                    reason="snapshot-to-quality child job status observed",
                    existing_job_id=existing_job_id,
                    existing_job_ids=existing_job_ids,
                    details={
                        "snapshot_id": snapshot.id,
                        "snapshot_status": snapshot.status,
                    },
                ),
            )

        return decisions

    def _gate_quality_to_project(self, session: Session) -> list[GateDecision]:
        return self._gate_quality_to_child(session, gate_name=GATE_QUALITY_TO_PROJECT)

    def _gate_quality_to_promote(self, session: Session) -> list[GateDecision]:
        return self._gate_quality_to_child(session, gate_name=GATE_QUALITY_TO_PROMOTE)

    def _gate_quality_to_child(
        self,
        session: Session,
        *,
        gate_name: str,
    ) -> list[GateDecision]:
        reports = tuple(session.scalars(select(SessionInterpretationQualityReport)).all())
        decisions: list[GateDecision] = []
        for report in reports:
            target = GateTarget(
                gate=gate_name,
                kind="session_interpretation_quality_report",
                identity={"quality_report_id": report.id},
            )
            if gate_name == GATE_QUALITY_TO_PROJECT:
                spec = project_memory_records_job_spec(
                    quality_report_id=report.id,
                    session_id=report.snapshot.session.session_id,
                    quality_job_id=report.job_id,
                    idempotency_key=project_memory_records_idempotency_key(report.id),
                )
            else:
                spec = promote_durable_memory_job_spec(
                    quality_report_id=report.id,
                    session_id=report.snapshot.session.session_id,
                    quality_job_id=report.job_id,
                    idempotency_key=promote_durable_memory_idempotency_key(report.id),
                )

            decision_status, existing_job_id, existing_job_ids = self._inspect_child_job_status(session, spec)
            if decision_status == "missing":
                decisions.append(
                    GateDecision(
                        target=target,
                        status="missing",
                        reason=f"quality-to-{gate_name.split('_')[-1]} child job is missing",
                        enqueue_spec=spec,
                        details={
                            "quality_report_id": report.id,
                        },
                    ),
                )
                continue

            decisions.append(
                GateDecision(
                    target=target,
                    status=decision_status,
                    reason=f"quality-to-{gate_name.split('_')[-1]} child job status observed",
                    existing_job_id=existing_job_id,
                    existing_job_ids=existing_job_ids,
                    details={
                        "quality_report_id": report.id,
                    },
                ),
            )

        return decisions

    def _inspect_child_job_status(
        self,
        session: Session,
        spec: EnqueueSpec,
    ) -> tuple[str, int | None, tuple[int, ...] | None]:
        if spec.idempotency_key is None:
            return "blocked", None, None

        jobs = tuple(
            session.scalars(
                select(Job)
                .where(
                    Job.kind == spec.kind,
                    Job.idempotency_key == spec.idempotency_key,
                )
                .order_by(Job.created_at.desc(), Job.id.desc()),
            ).all(),
        )
        if not jobs:
            return "missing", None, None

        latest_job = jobs[0]
        existing_job_ids = tuple(job.id for job in jobs)
        if len(existing_job_ids) <= 1:
            existing_job_ids = None

        if latest_job.status in (JOB_STATUS_QUEUED, JOB_STATUS_CLAIMED, JOB_STATUS_RUNNING):
            return "in_flight", latest_job.id, existing_job_ids
        if latest_job.status == JOB_STATUS_COMPLETED:
            return "satisfied", latest_job.id, existing_job_ids
        if latest_job.status == JOB_STATUS_FAILED:
            return "failed", latest_job.id, existing_job_ids
        if latest_job.status == JOB_STATUS_CANCELLED:
            return "blocked", latest_job.id, existing_job_ids

        return "blocked", latest_job.id, existing_job_ids
