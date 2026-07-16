"""Errors raised by the ensure-daemon client."""

from __future__ import annotations


class DaemonError(RuntimeError):
    """Base error for hub-daemon client failures."""


class DaemonUnavailableError(DaemonError):
    """The daemon could not be reached or spawned within the startup budget."""


class DaemonProtocolMismatchError(DaemonError):
    """A live daemon reports a protocol version the client cannot speak."""
