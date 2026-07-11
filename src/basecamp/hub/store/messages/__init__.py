"""The ``messages`` data object: schema, writes, reads, and status constants.

The status constants are re-exported so ``store.text`` (and service code) can
import them from ``..messages`` unchanged after the split.
"""

from __future__ import annotations

from .reader import MessagesReaderMixin
from .schema import (
    MESSAGE_STATUS_ACCEPTED,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_QUEUED,
    MESSAGE_STATUS_SENT,
    MESSAGE_STATUS_UNAVAILABLE,
    MESSAGE_STATUS_UNKNOWN,
    MESSAGE_STATUSES,
    MESSAGE_TERMINAL_DELIVERY_STATUSES,
    MessagesSchemaMixin,
)
from .writer import MessagesWriterMixin


class MessagesMixin(MessagesSchemaMixin, MessagesWriterMixin, MessagesReaderMixin):
    """All ``messages`` persistence, composed for the Store."""


__all__ = [
    "MESSAGE_STATUSES",
    "MESSAGE_STATUS_ACCEPTED",
    "MESSAGE_STATUS_FAILED",
    "MESSAGE_STATUS_QUEUED",
    "MESSAGE_STATUS_SENT",
    "MESSAGE_STATUS_UNAVAILABLE",
    "MESSAGE_STATUS_UNKNOWN",
    "MESSAGE_TERMINAL_DELIVERY_STATUSES",
    "MessagesMixin",
]
