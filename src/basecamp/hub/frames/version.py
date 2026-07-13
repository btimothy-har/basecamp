"""Wire protocol version + the shared frame envelope both frame modules build on.

Kept in its own module so ``swarm``/``broker`` can reference ``PROTOCOL_VERSION``
and ``ProtocolFrame`` without importing the package ``__init__`` (which imports them).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Gates every client-visible daemon capability, not just WebSocket frame shapes.
# This includes HTTP endpoints like /runs/summary, so stale daemons restart.
# v19: workstream create/attach/update request/ack frames.
# v20: thread_report frame — top-level session ships its raw thread to the daemon.
# v21: register frame gains repo + worktree_label identity facets.
# v22: revise_workstream content-versioning frames + /workstreams detail carries version history.
PROTOCOL_VERSION = 22


class ProtocolFrame(BaseModel):
    """Base for every wire frame: carries the version envelope field once.

    ``v`` defaults to ``PROTOCOL_VERSION`` so no frame model or construction site
    repeats it. ``serialize_frame`` re-stamps ``v`` on the wire because
    ``model_dump(exclude_unset=True)`` would otherwise drop the defaulted value.
    """

    v: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
