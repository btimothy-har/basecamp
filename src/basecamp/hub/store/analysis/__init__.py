"""The ``analysis`` data object: schema, write (upsert), and read.

Re-exports ``AnalysisRow`` so callers can import the read type from
``..store.analysis`` unchanged.
"""

from __future__ import annotations

from .reader import AnalysisReaderMixin, AnalysisRow
from .schema import AnalysisSchemaMixin
from .writer import AnalysisWriterMixin


class AnalysisMixin(AnalysisSchemaMixin, AnalysisWriterMixin, AnalysisReaderMixin):
    """All ``analysis`` persistence, composed for the Store."""


__all__ = ["AnalysisMixin", "AnalysisRow"]
