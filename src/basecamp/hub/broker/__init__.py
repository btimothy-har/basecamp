"""The companion-analysis broker: raw-thread ingest + the warm analyzer.

The hub's second domain (beside the agent ``swarm``): it persists each top-level
session's raw thread (``handle_thread_report``) and runs the warm analyzer over
it (``AnalysisScheduler``).
"""

from __future__ import annotations

from .analysis import AnalysisScheduler
from .thread_report import handle_thread_report

__all__ = ["AnalysisScheduler", "handle_thread_report"]
