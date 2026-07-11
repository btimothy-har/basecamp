"""The ``raw_pi_thread`` data object: schema, writes, and reads.

Re-exports the node input type and the head/branch result types so
``from ..store.raw_pi_thread import RawPiThreadNode`` (etc.) keeps working.
"""

from __future__ import annotations

from .reader import RawPiThread, RawPiThreadReaderMixin, RawPiThreadRow
from .schema import RawPiThreadSchemaMixin
from .writer import RawPiThreadNode, RawPiThreadWriterMixin


class RawPiThreadMixin(RawPiThreadSchemaMixin, RawPiThreadWriterMixin, RawPiThreadReaderMixin):
    """All ``raw_pi_thread`` persistence, composed for the Store."""


__all__ = ["RawPiThread", "RawPiThreadMixin", "RawPiThreadNode", "RawPiThreadRow"]
