"""The Claude Code session-lifecycle hub.

This package is everything the Claude Code integration needs from the hub and
nothing it does not: runtime paths, the sessions + episodes store, the
HTTP-over-UDS daemon (health + register/end/list), and the ensure-daemon client
the hooks call. Its wire contract is Claude-owned
(:mod:`basecamp.hub.claude.contract`).
"""

from __future__ import annotations
