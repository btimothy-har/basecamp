"""Discover subagent transcript sidecars for a main Claude Code transcript.

Subagents — ``Task``/``Agent`` tool calls, and workflow fan-out — write their own
turns to sidecar JSONL files under ``<session_id>/subagents/`` rather than inlining
them in the main transcript, which keeps only the final tool_result string. The
sidecars are therefore the *sole* record of a subagent's actual work, so ingest
sweeps them alongside the main file.

Each sidecar carries its own uuid space (no collision with the main DAG) and never
links into the main thread via ``parentUuid``. The tie to the spawning call is
out-of-band:

- the ``agent-<id>.jsonl`` filename (and every line's ``agentId``) identifies the
  subagent;
- the sibling ``agent-<id>.meta.json``'s ``toolUseId`` points at the parent
  ``Task``/``Agent`` tool_use block in the main thread. (Workflow fan-out agents
  have no ``toolUseId`` — they are spawned by the orchestrator, not a main-thread
  tool call — so it is ``None`` there.)

Discovery is recursive (``rglob``) so it captures both direct subagents
(``subagents/agent-*.jsonl``) and workflow-nested ones
(``subagents/workflows/wf_*/agent-*.jsonl``); the ``agent-*`` glob naturally skips
``journal.jsonl`` (which carries no ``uuid`` and would be dropped by the parser
anyway). Everything here is best-effort: a missing/unreadable tree yields nothing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Sidecar:
    """One subagent sidecar file plus its out-of-band parent-linkage keys."""

    path: Path
    agent_id: str
    tool_use_id: str | None


def subagents_dir(main_transcript_path: Path) -> Path:
    """The ``subagents`` dir for a main transcript ``<dir>/<session_id>.jsonl``."""

    # ``session_id`` never contains a dot, so ``with_suffix("")`` drops only ``.jsonl``.
    return main_transcript_path.with_suffix("") / "subagents"


def _tool_use_id(sidecar_path: Path) -> str | None:
    """Read the parent ``toolUseId`` from the sidecar's sibling ``.meta.json``."""

    meta_path = sidecar_path.with_name(f"{sidecar_path.stem}.meta.json")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    tool_use_id = meta.get("toolUseId") if isinstance(meta, dict) else None
    return tool_use_id if isinstance(tool_use_id, str) and tool_use_id else None


def sidecar_for(path: Path) -> Sidecar:
    """Build a :class:`Sidecar` from one ``agent-<id>.jsonl`` path.

    The agent id is the filename stem minus its ``agent-`` prefix; the parent
    ``tool_use_id`` is read from the sibling ``.meta.json`` (``None`` when absent,
    as for orchestrator-spawned workflow agents). Used both by the full sweep and
    by the SubagentStop targeted ingest, which knows a single sidecar's path.
    """

    return Sidecar(path=path, agent_id=path.stem.removeprefix("agent-"), tool_use_id=_tool_use_id(path))


def discover_sidecars(main_transcript_path: Path) -> list[Sidecar]:
    """Find every subagent sidecar for a main transcript (direct + workflow-nested).

    Returns an empty list when the session spawned no subagents or the tree is
    unreadable — never raises.
    """

    root = subagents_dir(main_transcript_path)
    if not root.is_dir():
        return []
    try:
        paths = sorted(root.rglob("agent-*.jsonl"))
    except OSError as exc:
        logger.warning("subagent sidecar discovery failed under %s: %s", root, exc)
        return []
    return [sidecar_for(p) for p in paths]
