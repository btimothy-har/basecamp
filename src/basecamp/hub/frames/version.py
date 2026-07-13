"""Wire protocol version — the leaf both frame modules import.

Kept in its own module so ``swarm``/``broker`` can reference ``PROTOCOL_VERSION``
without importing the package ``__init__`` (which imports them).
"""

from __future__ import annotations

# Gates every client-visible daemon capability, not just WebSocket frame shapes.
# This includes HTTP endpoints like /runs/summary, so stale daemons restart.
# v19: workstream create/attach/update request/ack frames.
# v20: thread_report frame — top-level session ships its raw thread to the daemon.
# v21: register frame gains repo + worktree_label identity facets.
# v22: revise_workstream content-versioning frames + /workstreams detail carries version history.
PROTOCOL_VERSION = 22
