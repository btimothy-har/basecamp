"""The ``workstreams`` data object: schema, writes, and reads."""

from __future__ import annotations

from .reader import WorkstreamsReaderMixin
from .schema import WorkstreamsSchemaMixin
from .writer import WorkstreamsWriterMixin


class WorkstreamsMixin(WorkstreamsSchemaMixin, WorkstreamsWriterMixin, WorkstreamsReaderMixin):
    """All ``workstreams`` persistence, composed for the Store."""


__all__ = ["WorkstreamsMixin"]
