"""Companion analysis: the daemon-side reducer, analyzer seam, and scheduler.

The reducer is the only reader of pi ``SessionEntry`` content; the analyzer is a
swappable seam with a provisional PydanticAI implementation; the scheduler runs
the analyzer reactively when fresh turns land.
"""

from __future__ import annotations

from .analyzer import Analyzer, PydanticAIAnalyzer, build_prompt
from .reducer import reduce_thread
from .scheduler import AnalysisScheduler
from .sections import AnalysisSections

__all__ = [
    "AnalysisScheduler",
    "AnalysisSections",
    "Analyzer",
    "PydanticAIAnalyzer",
    "build_prompt",
    "reduce_thread",
]
