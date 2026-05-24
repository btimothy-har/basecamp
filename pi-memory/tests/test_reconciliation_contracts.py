from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pi_memory.pipeline.reconciliation import (
    EnqueueSpec,
    GateDecision,
    GateStatus,
    GateTarget,
    ReconciliationReport,
    ReconciliationRunOptions,
)
from pydantic import ValidationError


def gate_target() -> GateTarget:
    return GateTarget(gate="quality_gate", kind="snapshot", identity={"snapshot_id": "123"})


def decision(*, status: GateStatus, reason: str) -> GateDecision:
    return GateDecision(target=gate_target(), status=status, reason=reason)


def test_reconciliation_import_and_defaults() -> None:
    run = ReconciliationRunOptions()
    assert run.enqueue_missing is False
    assert run.gate_names is None

    payload_a = EnqueueSpec(kind="interpret_session")
    payload_b = EnqueueSpec(kind="interpret_session")

    payload_a.payload_json["foo"] = "bar"
    assert payload_b.payload_json == {}

    decision_a = GateDecision(target=gate_target(), status="missing", reason="missing job")
    decision_b = GateDecision(target=gate_target(), status="missing", reason="already enqueued")

    decision_a.details["foo"] = "bar"
    assert decision_b.details == {}


def test_contracts_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        EnqueueSpec(kind="interpret_session", unexpected="value")

    with pytest.raises(ValidationError):
        GateDecision(
            target=gate_target(),
            status="missing",
            reason="unexpected field",
            unknown_field="bad",
        )

    with pytest.raises(ValidationError):
        ReconciliationReport(as_of=datetime.now(tz=UTC), decisions=(), unknown_field=123)


def test_gate_status_counts() -> None:
    report = ReconciliationReport(
        as_of=datetime.now(tz=UTC),
        decisions=(
            decision(status="satisfied", reason="already done"),
            decision(status="missing", reason="needs enqueue"),
            decision(status="in_flight", reason="running"),
            decision(status="blocked", reason="blocked"),
            decision(status="failed", reason="failed"),
            decision(status="missing", reason="still missing"),
        ),
        enqueued_job_ids=(12, 13),
    )

    assert report.total_decisions == 6
    assert report.satisfied_count == 1
    assert report.missing_count == 2
    assert report.in_flight_count == 1
    assert report.blocked_count == 1
    assert report.failed_count == 1


def test_gate_decision_enqueue_convenience_property() -> None:
    target = gate_target()

    assert GateDecision(
        target=target,
        status="missing",
        reason="not present",
        enqueue_spec=EnqueueSpec(kind="interpret_session"),
    ).can_enqueue

    assert not GateDecision(
        target=target,
        status="satisfied",
        reason="already complete",
        enqueue_spec=EnqueueSpec(kind="interpret_session"),
    ).can_enqueue
    assert not GateDecision(target=target, status="missing", reason="queued already", existing_job_id=7).can_enqueue


def test_reconciliation_report_enqueued_ids_defaults_are_isolated() -> None:
    first = ReconciliationReport(as_of=datetime.now(tz=UTC))
    second = ReconciliationReport(as_of=datetime.now(tz=UTC))

    assert first.enqueued_job_ids == ()
    assert second.enqueued_job_ids == ()


def test_run_options_max_enqueues_validation() -> None:
    with pytest.raises(ValidationError):
        ReconciliationRunOptions(max_enqueues=0)
