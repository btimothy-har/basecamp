"""The ``transcript_nodes`` data object: the raw Claude Code transcript DAG.

One row per transcript node, keyed by the node's own ``uuid``. A Claude Code
transcript is an append-only JSONL of DAG nodes (``user`` | ``assistant`` |
``system`` | ``attachment``, each carrying ``uuid`` + ``parentUuid``); this table
stores each such line verbatim (``line_json``) with the few fields we route on
lifted into columns. UI/state markers without a ``uuid`` are never ingested.

The ``uuid`` primary key + ``INSERT OR IGNORE`` is the whole design:

- **Idempotent re-ingest.** PreCompact and SessionEnd both read the full file; a
  node already stored is silently ignored, so coarse full-file triggers never
  duplicate. First writer wins — a node keeps the ``session_id``/``episode_id`` of
  whoever ingested it first.
- **Forks dedup themselves.** A forked session's transcript is a verbatim copy of
  its parent's nodes (same ``uuid``s, ``sessionId`` rewritten per file); ingesting
  it inserts only the fork's genuinely new nodes. Lineage is therefore derivable
  from ``uuid`` overlap across sessions — no ``forked_from`` column needed.

Reconstruction walks ``parent_uuid`` (bridged across compaction boundaries by
``logical_parent_uuid``), **not** the ``session_id`` column: a node shared by a
fork carries only its first ingester's session label. This mixin only stores; it
never interprets the DAG.

**Subagent nodes** (``is_sidechain = 1``) come from sidecar files that carry their
own uuid space and never link into the main DAG via ``parent_uuid``. Their only
tie to the spawning session is out-of-band, so two nullable columns capture it:
``source_agent_id`` (the sidecar's agent id) groups one subagent's nodes, and
``source_tool_use_id`` (the sidecar's ``meta.json`` ``toolUseId``) points at the
parent ``Task``/``Agent`` tool_use block in the main thread — the key that lets a
subagent's parent be identified later. Both are ``NULL`` for main-thread nodes.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any

_INSERT_NODE = """
    INSERT OR IGNORE INTO transcript_nodes (
        uuid, session_id, parent_uuid, logical_parent_uuid, episode_id,
        type, is_sidechain, source_agent_id, source_tool_use_id,
        timestamp, seq, line_json, first_seen_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class TranscriptsMixin:
    """Verbatim, uuid-keyed storage of Claude Code transcript DAG nodes."""

    def _init_transcripts_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS transcript_nodes (
                uuid TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                parent_uuid TEXT,
                logical_parent_uuid TEXT,
                episode_id TEXT,
                type TEXT,
                is_sidechain INTEGER,
                source_agent_id TEXT,
                source_tool_use_id TEXT,
                timestamp TEXT,
                seq INTEGER,
                line_json TEXT NOT NULL,
                first_seen_at TEXT NOT NULL
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_transcript_nodes_session ON transcript_nodes(session_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_transcript_nodes_parent ON transcript_nodes(parent_uuid)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_transcript_nodes_tool_use ON transcript_nodes(source_tool_use_id)"
        )

    def record_nodes(
        self,
        *,
        session_id: str,
        episode_id: str | None,
        nodes: Iterable[Mapping[str, Any]],
        source_agent_id: str | None = None,
        source_tool_use_id: str | None = None,
    ) -> int:
        """Bulk-insert parsed transcript ``nodes``; return how many were newly stored.

        Every node is stamped with the file's ``session_id`` and the episode live at
        ingest time (both best-effort labels, never a reconstruction key). Re-ingested
        and fork-copied nodes collide on the ``uuid`` primary key and are ignored, so
        the return value is the count of genuinely new nodes — 0 when nothing changed.

        ``source_agent_id``/``source_tool_use_id`` are the sidecar's parent-linkage
        keys, stamped on every node of one subagent file and left ``NULL`` for the
        main thread.
        """

        now = self._now()
        rows = [
            (
                node["uuid"],
                session_id,
                node.get("parent_uuid"),
                node.get("logical_parent_uuid"),
                episode_id,
                node.get("type"),
                node.get("is_sidechain"),
                source_agent_id,
                source_tool_use_id,
                node.get("timestamp"),
                node.get("seq"),
                node["line_json"],
                now,
            )
            for node in nodes
        ]
        if not rows:
            return 0
        with self._connect() as connection:
            before = connection.total_changes
            connection.executemany(_INSERT_NODE, rows)
            return connection.total_changes - before

    def has_agent_nodes(self, session_id: str, source_agent_id: str) -> bool:
        """Whether one subagent's sidecar has already been ingested for ``session_id``.

        The anti-repeat primitive shared by both sidecar triggers: SubagentStop
        ingests a single completed sidecar promptly, and the SessionEnd sweep skips
        any agent this returns ``True`` for so it never re-parses that file. Purely a
        parse-cost guard — ``INSERT OR IGNORE`` already makes a repeat harmless — and
        it reads only stored data, so no new bookkeeping state is introduced.
        """

        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM transcript_nodes WHERE session_id = ? AND source_agent_id = ? LIMIT 1",
                (session_id, source_agent_id),
            ).fetchone()
        return row is not None

    def count_transcript_nodes(self, session_id: str | None = None) -> int:
        """Return the stored node count, overall or for one ``session_id``."""

        with self._connect() as connection:
            if session_id is None:
                row = connection.execute("SELECT COUNT(*) FROM transcript_nodes").fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) FROM transcript_nodes WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
        return int(row[0])
