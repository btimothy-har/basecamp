"""Daemon-side transcript ingest: read the file, store its nodes.

Unlike the Pi hub — where the session *pushed* its thread over a WebSocket — a
Claude Code transcript is a file on disk the daemon already knows the path to
(captured at SessionStart). So ingest is daemon-local: the PreCompact/SessionEnd
hook is a thin trigger, and the daemon reads and parses the file itself.

Subagent work is never inlined in the main file, so the sidecars under
``<session_id>/subagents/`` (see :mod:`.sidecars`) are the sole record of it; each
sidecar's nodes are stamped with their parent-linkage keys. Two triggers reach
them, keyed off the ingest call's mode:

- **SubagentStop** — a single subagent just finished, so ``agent_transcript_path``
  names exactly one complete sidecar: ingest that file alone (targeted mode).
  Prompt, and never touches an in-flight peer.
- **SessionEnd** — every subagent is complete, so ``sweep_sidecars`` walks the whole
  ``subagents/`` tree and ingests each sidecar not already stored (the backstop that
  needs only ``session_id`` and guarantees capture even if SubagentStop never fired).
- **PreCompact** — main file only (``sweep_sidecars`` off): a sidecar may be
  mid-write, and SessionEnd will sweep it once it is done.

The skip is :meth:`SessionStore.has_agent_nodes`, so a sidecar is parsed once across
both triggers even though ``INSERT OR IGNORE`` would already make a repeat harmless.

Two layers:

- :func:`ingest_session` — the pure, synchronous unit: resolve the path(s), parse the
  main file and/or sidecars, ``INSERT OR IGNORE`` the nodes, return how many were
  new. Fully testable with a real store and a temp file; safe to call repeatedly
  (idempotent by ``uuid``).
- :class:`IngestScheduler` — fires that work as a background task on the daemon's
  event loop so the triggering HTTP request returns immediately. A large transcript
  parse must not block the hook (which times out fast) nor be cancelled when the
  hook disconnects, so the route resolves the path/episode synchronously and hands
  the slow parse to this scheduler.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

from .sidecars import Sidecar, discover_sidecars, sidecar_for
from .store import SessionStore
from .transcript import parse_transcript

logger = logging.getLogger(__name__)

IngestFn = Callable[..., int]


def ingest_session(
    store: SessionStore,
    *,
    session_id: str,
    transcript_path: str | None,
    episode_id: str | None,
    sweep_sidecars: bool = False,
    agent_transcript_path: str | None = None,
) -> int:
    """Parse a transcript and/or its subagent sidecars and store every node.

    Returns the total number of newly stored nodes. Best-effort and idempotent: a file
    that is missing, unreadable, unparseable, or whose store write loses a contended
    lock logs and contributes 0 rather than raising, and re-ingesting unchanged files
    inserts nothing (every node collides on its ``uuid`` primary key). Three modes,
    selected by the caller's trigger:

    - ``agent_transcript_path`` set (SubagentStop): ingest that one complete sidecar
      and nothing else — the main file is captured by its own triggers.
    - ``sweep_sidecars`` true (SessionEnd): ingest the main file, then every sidecar
      under ``subagents/`` not already stored.
    - neither (PreCompact): ingest the main file only.

    The main file and each sidecar are read *and stored* independently, so a failure
    on any one of them (missing, unparseable, or a contended write) never suppresses
    the others.
    """

    if agent_transcript_path:
        sidecar = sidecar_for(Path(agent_transcript_path).expanduser())
        return _ingest_sidecar(store, sidecar, session_id=session_id, episode_id=episode_id)

    if not transcript_path:
        logger.warning("transcript ingest skipped: no path for session %s", session_id)
        return 0
    main_path = Path(transcript_path).expanduser()
    total = _ingest_file(store, main_path, session_id=session_id, episode_id=episode_id)
    if sweep_sidecars:
        for sidecar in discover_sidecars(main_path):
            total += _ingest_sidecar(store, sidecar, session_id=session_id, episode_id=episode_id)
    return total


def _ingest_sidecar(
    store: SessionStore,
    sidecar: Sidecar,
    *,
    session_id: str,
    episode_id: str | None,
) -> int:
    """Ingest one subagent sidecar, skipping it if already stored for this session."""

    if store.has_agent_nodes(session_id, sidecar.agent_id):
        return 0
    return _ingest_file(
        store,
        sidecar.path,
        session_id=session_id,
        episode_id=episode_id,
        source_agent_id=sidecar.agent_id,
        source_tool_use_id=sidecar.tool_use_id,
    )


def _ingest_file(
    store: SessionStore,
    path: Path,
    *,
    session_id: str,
    episode_id: str | None,
    source_agent_id: str | None = None,
    source_tool_use_id: str | None = None,
) -> int:
    """Parse one JSONL file and record its nodes; 0 on any single-file failure.

    Fully self-contained per file: a missing/unreadable file, a parse/decode error the
    resilient parser could not itself absorb, *and* a store-write failure all degrade
    this one file to 0. Nothing here may propagate — the whole point is that a
    SessionEnd sweep processes each file independently, so one bad file must never
    abort the loop and silently drop every remaining sidecar (SessionEnd is the sole
    sweep trigger, so that loss would be permanent, not merely delayed).
    """

    if not path.is_file():
        logger.warning("transcript ingest skipped: no file at %s (session %s)", path, session_id)
        return 0
    try:
        nodes = parse_transcript(path)
        return store.record_nodes(
            session_id=session_id,
            episode_id=episode_id,
            nodes=nodes,
            source_agent_id=source_agent_id,
            source_tool_use_id=source_tool_use_id,
        )
    except (OSError, ValueError, sqlite3.OperationalError) as exc:
        # OSError: file unreadable after the is_file() check. ValueError: an unabsorbed
        # parse/decode error. OperationalError: the record_nodes write lost the (WAL is
        # still single-writer) writer-writer race past busy_timeout — the same failure
        # the /end route guards. Any of them degrades this one file, never the sweep.
        logger.warning("transcript ingest failed for %s: %s", path, exc)
        return 0


class IngestScheduler:
    """Run :func:`ingest_session` as a fire-and-forget task on the event loop."""

    def __init__(self, store: SessionStore, *, ingest: IngestFn = ingest_session) -> None:
        self._store = store
        self._ingest = ingest
        self._tasks: set[asyncio.Task[int]] = set()

    def schedule(
        self,
        *,
        session_id: str,
        transcript_path: str | None,
        episode_id: str | None,
        sweep_sidecars: bool = False,
        agent_transcript_path: str | None = None,
    ) -> None:
        """Schedule a background ingest. Returns at once; keeps a strong task ref."""

        task = asyncio.create_task(
            self._run(
                session_id=session_id,
                transcript_path=transcript_path,
                episode_id=episode_id,
                sweep_sidecars=sweep_sidecars,
                agent_transcript_path=agent_transcript_path,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(
        self,
        *,
        session_id: str,
        transcript_path: str | None,
        episode_id: str | None,
        sweep_sidecars: bool = False,
        agent_transcript_path: str | None = None,
    ) -> int:
        try:
            count = await asyncio.to_thread(
                self._ingest,
                self._store,
                session_id=session_id,
                transcript_path=transcript_path,
                episode_id=episode_id,
                sweep_sidecars=sweep_sidecars,
                agent_transcript_path=agent_transcript_path,
            )
        except Exception:  # noqa: BLE001 - a background ingest must never crash the daemon
            logger.exception("transcript ingest task failed for session %s", session_id)
            return 0
        logger.info("ingested %d new transcript node(s) for session %s", count, session_id)
        return count

    async def drain(self) -> None:
        """Await all in-flight ingest tasks (shutdown / test helper)."""

        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
