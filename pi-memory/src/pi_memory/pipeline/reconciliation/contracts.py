"""Contracts for pipeline reconciliation decisions and reporting."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

PayloadValue = str | int | float | bool | None
IdentityValue = str | int | float | bool | None

GateName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

GateStatus = Literal["satisfied", "missing", "in_flight", "blocked", "failed"]


class GateTarget(BaseModel):
    """Stable identity for a reconciliation gate target."""

    model_config = ConfigDict(extra="forbid")

    gate: GateName
    kind: GateName
    identity: dict[str, IdentityValue] = Field(default_factory=dict)


class EnqueueSpec(BaseModel):
    """Request shape for enqueuing a job during reconciliation."""

    model_config = ConfigDict(extra="forbid")

    kind: GateName
    payload_json: dict[str, PayloadValue] = Field(default_factory=dict)
    priority: int = 0
    due_at: datetime | None = None
    max_attempts: int = 3
    idempotency_key: str | None = None


class GateDecision(BaseModel):
    """Decision describing whether a reconciliation gate is satisfiable."""

    model_config = ConfigDict(extra="forbid")

    target: GateTarget
    status: GateStatus
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)
    enqueue_spec: EnqueueSpec | None = None
    existing_job_id: int | None = None
    existing_job_ids: tuple[int, ...] | None = None

    @property
    def can_enqueue(self) -> bool:
        """Whether this decision is eligible for job enqueue."""

        return (
            self.status == "missing"
            and self.enqueue_spec is not None
            and self.existing_job_id is None
            and not self.existing_job_ids
        )


class ReconciliationRunOptions(BaseModel):
    """Inputs controlling one reconciliation run."""

    model_config = ConfigDict(extra="forbid")

    enqueue_missing: bool = False
    gate_names: tuple[GateName, ...] | None = None
    max_enqueues: int | None = Field(default=None, ge=1)
    as_of: datetime | None = None


class ReconciliationReport(BaseModel):
    """Outcome report for a reconciliation run."""

    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    decisions: tuple[GateDecision, ...] = Field(default_factory=tuple)
    enqueued_job_ids: tuple[int, ...] = Field(default_factory=tuple)

    @property
    def satisfied_count(self) -> int:
        return sum(1 for decision in self.decisions if decision.status == "satisfied")

    @property
    def missing_count(self) -> int:
        return sum(1 for decision in self.decisions if decision.status == "missing")

    @property
    def in_flight_count(self) -> int:
        return sum(1 for decision in self.decisions if decision.status == "in_flight")

    @property
    def blocked_count(self) -> int:
        return sum(1 for decision in self.decisions if decision.status == "blocked")

    @property
    def failed_count(self) -> int:
        return sum(1 for decision in self.decisions if decision.status == "failed")

    @property
    def total_decisions(self) -> int:
        return len(self.decisions)


__all__ = [
    "GateDecision",
    "GateStatus",
    "GateTarget",
    "EnqueueSpec",
    "ReconciliationReport",
    "ReconciliationRunOptions",
]

