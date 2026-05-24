"""Pipeline reconciliation contracts and entry points."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from pi_memory.pipeline.reconciliation.contracts import (
    EnqueueSpec,
    GateDecision,
    GateStatus,
    GateTarget,
    ReconciliationReport,
    ReconciliationRunOptions,
)

if TYPE_CHECKING:
    from pi_memory.pipeline.reconciliation.reconciler import Reconciler


def __getattr__(name: str) -> Any:
    if name == "Reconciler":
        return getattr(import_module("pi_memory.pipeline.reconciliation.reconciler"), name)
    raise AttributeError(name)


__all__ = [
    "EnqueueSpec",
    "GateDecision",
    "GateStatus",
    "GateTarget",
    "ReconciliationReport",
    "ReconciliationRunOptions",
    "Reconciler",
]
