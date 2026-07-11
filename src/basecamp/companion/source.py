"""Merged data source for the companion dashboard.

Combines the authoritative goal-cycle store (an mtime-watched file, via cycles.py)
with the daemon-sourced analysis (fetched each poll from ``GET /analysis/{session_id}``)
into one DashboardModel. Best-effort: a missing goal file yields empty goals, and a
None analysis fetch (daemon unreachable / not ready) retains the last-shown analysis
rather than blanking the panel.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from basecamp.companion.analysis import CompanionAnalysis
from basecamp.companion.cycles import load_goal_cycles, to_display_goals
from basecamp.companion.snapshot import CompanionGoal

AnalysisFetcher = Callable[[], CompanionAnalysis | None]


@dataclass
class DashboardModel:
    """Merged dashboard payload: authoritative goals + daemon analysis."""

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
    """Watches the goal-cycle store and fetches analysis from the daemon on each poll."""

    def __init__(self, tasks_path: Path, analysis_fetcher: AnalysisFetcher) -> None:
        self._tasks_path = tasks_path
        self._analysis_fetcher = analysis_fetcher
        self._tasks_sig: tuple[bool, int | None] | None = None
        self._goals: list[CompanionGoal] = []
        self._analysis: CompanionAnalysis | None = None

    def poll(self) -> DashboardModel | None:
        """Return the merged model when goals or analysis changed since last poll, else None."""

        changed = False

        tasks_sig = _file_signature(self._tasks_path)
        if tasks_sig != self._tasks_sig:
            self._tasks_sig = tasks_sig
            self._goals = to_display_goals(load_goal_cycles(self._tasks_path)) if tasks_sig[0] else []
            changed = True

        # A None fetch means the daemon is unreachable or hasn't produced analysis yet —
        # it is NOT a signal to clear an already-shown dashboard. Only a fresh non-None
        # result updates the panel, so a transient daemon blip never blanks it.
        analysis = self._analysis_fetcher()
        if analysis is not None and analysis != self._analysis:
            self._analysis = analysis
            changed = True

        if not changed:
            return None
        return DashboardModel(goals=list(self._goals), analysis=self._analysis)
