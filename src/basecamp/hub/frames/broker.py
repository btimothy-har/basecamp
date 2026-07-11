"""Companion-broker protocol frames: the raw pi thread report (v20)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .version import PROTOCOL_VERSION


class ThreadReportNode(BaseModel):
    """One pi session entry; ``entry_json`` is opaque and never parsed by the daemon."""

    id: str
    parent_id: str | None
    entry_json: str


class ThreadReportFrame(BaseModel):
    """Raw session thread pushed by a top-level session at end of turn.

    The extension splits ``getBranch()`` into per-entry ``nodes`` (envelope
    extracted extension-side) so the daemon stores immutable nodes without
    parsing pi content. ``session_id``/``session_file`` are pi's own id and
    ``.jsonl`` transcript path (see docs/design/companion-daemon-broker.md).
    """

    type: Literal["thread_report"]
    v: Literal[PROTOCOL_VERSION]
    node_id: str
    session_id: str
    session_file: str | None
    leaf_id: str | None
    nodes: list[ThreadReportNode]
