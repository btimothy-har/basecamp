"""The ``runs`` data object: schema (runs + run_events), writes, and reads."""

from __future__ import annotations

from .reader import RunsReaderMixin
from .schema import RunsSchemaMixin
from .writer import RunsWriterMixin


class RunsMixin(RunsSchemaMixin, RunsWriterMixin, RunsReaderMixin):
    """All ``runs`` persistence, composed for the Store."""


__all__ = ["RunsMixin"]
