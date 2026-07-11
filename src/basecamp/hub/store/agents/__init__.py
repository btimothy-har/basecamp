"""The ``agents`` data object: schema, writes, and reads."""

from __future__ import annotations

from .reader import AgentsReaderMixin
from .schema import AgentsSchemaMixin
from .writer import AgentsWriterMixin


class AgentsMixin(AgentsSchemaMixin, AgentsWriterMixin, AgentsReaderMixin):
    """All ``agents`` persistence, composed for the Store."""


__all__ = ["AgentsMixin"]
