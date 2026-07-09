"""Merged, mtime-watched data source for the companion dashboard.

Combines the two payloads the dashboard renders — the authoritative goal-cycle
store (read via cycles.py) and the inferred analysis sidecar (analysis.py) —
into one DashboardModel, reloading only the file that changed. Best-effort:
a missing or unreadable file just yields empty/partial data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from basecamp.companion.analysis import CompanionAnalysis, load_analysis
from basecamp.companion.cycles import load_goal_cycles, to_display_goals
from basecamp.companion.snapshot import CompanionGoal


@dataclass
class DashboardModel:
    """Merged dashboard payload: authoritative goals + inferred analysis."""

    goals: list[CompanionGoal] = field(default_factory=list)
    analysis: CompanionAnalysis | None = None


def _file_signature(path: Path) -> tuple[bool, int | None]:
    try:
        if path.exists():
            return True, path.stat().st_mtime_ns
    except OSError:
        pass
    return False, None


class DashboardSource:
    """Watches the goal-cycle store + analysis sidecar, merging them on change."""

    def __init__(self, tasks_path: Path, analysis_path: Path) -> None:
        self._tasks_path = tasks_path
        self._analysis_path = analysis_path
        self._tasks_sig: tuple[bool, int | None] | None = None
        self._analysis_sig: tuple[bool, int | None] | None = None
        self._goals: list[CompanionGoal] = []
        self._analysis: CompanionAnalysis | None = None

    def poll(self) -> DashboardModel | None:
        """Return the merged model when either source changed since last poll, else None."""

        changed = False

        tasks_sig = _file_signature(self._tasks_path)
        if tasks_sig != self._tasks_sig:
            self._tasks_sig = tasks_sig
            self._goals = to_display_goals(load_goal_cycles(self._tasks_path)) if tasks_sig[0] else []
            changed = True

        analysis_sig = _file_signature(self._analysis_path)
        if analysis_sig != self._analysis_sig:
            self._analysis_sig = analysis_sig
            self._analysis = load_analysis(self._analysis_path) if analysis_sig[0] else None
            changed = True

        if not changed:
            return None
        return DashboardModel(goals=list(self._goals), analysis=self._analysis)
