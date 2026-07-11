"""SQLite persistence for raw pi session threads, stored node by node.

pi already persists the full raw thread in its ``.jsonl`` transcript; this store
holds each immutable entry once (keyed by ``entry_id``), inserting only new nodes
each turn, so it can dedup, query, and join across sessions/trees. The per-session
head row records the current ``leaf_id`` plus pi's ``session_id`` and
``session_file`` (transcript path). Node ``entry_json`` is opaque — the daemon
never parses the pi SessionEntry shape (see docs/design/companion-daemon-broker.md).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RawPiThreadRow:
    """Per-session head: the current leaf plus pi's session pointers."""

    owner_id: str
    session_id: str
    session_file: str | None
    leaf_id: str | None
    latest_seq: int
    updated_at: str


@dataclass(frozen=True)
class RawPiThreadNode:
    """One thread entry to persist; ``entry_json`` is stored verbatim."""

    entry_id: str
    parent_id: str | None
    entry_json: str


@dataclass(frozen=True)
class RawPiThread:
    """A reconstructed session thread, entries as ``entry_json`` root→leaf.

    ``live`` is the current branch (walked from the head's ``leaf_id``).
    ``abandoned`` holds each rewound branch (root→leaf), empty unless requested —
    the optional / back-pocket "roads not taken", kept separate from the main thread.
    """

    live: list[str]
    abandoned: list[list[str]] = field(default_factory=list)


def _reconstruct_branch(connection: sqlite3.Connection, owner_id: str, leaf_id: str) -> list[str]:
    """Walk ``parent_id`` up from ``leaf_id``, returning ``entry_json`` root→leaf."""

    rows = connection.execute(
        """
        WITH RECURSIVE branch(entry_id, parent_id, entry_json, depth) AS (
            SELECT entry_id, parent_id, entry_json, 0
            FROM raw_pi_thread_node
            WHERE owner_id = ? AND entry_id = ?
            UNION ALL
            SELECT n.entry_id, n.parent_id, n.entry_json, b.depth + 1
            FROM raw_pi_thread_node n
            JOIN branch b ON n.entry_id = b.parent_id
            WHERE n.owner_id = ?
        )
        SELECT entry_json FROM branch ORDER BY depth DESC
        """,
        (owner_id, leaf_id, owner_id),
    ).fetchall()
    return [row[0] for row in rows]


class RawPiThreadMixin:
    """Store mixin for the ``raw_pi_thread`` head + ``raw_pi_thread_node`` tables."""

    def record_raw_pi_thread(
        self,
        *,
        owner_id: str,
        session_id: str,
        session_file: str | None,
        leaf_id: str | None,
        nodes: list[RawPiThreadNode],
        now: str | None = None,
    ) -> int:
        """Bump the session head and insert only new nodes; return the new seq."""

        timestamp = now or self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT latest_seq FROM raw_pi_thread WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()
            seq = (row[0] + 1) if row is not None else 1
            connection.execute(
                """
                INSERT INTO raw_pi_thread (owner_id, session_id, session_file, leaf_id, latest_seq, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_id)
                DO UPDATE SET
                    session_id = excluded.session_id,
                    session_file = excluded.session_file,
                    leaf_id = excluded.leaf_id,
                    latest_seq = excluded.latest_seq,
                    updated_at = excluded.updated_at
                """,
                (owner_id, session_id, session_file, leaf_id, seq, timestamp),
            )
            connection.executemany(
                """
                INSERT INTO raw_pi_thread_node (owner_id, entry_id, parent_id, first_seen_seq, entry_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(owner_id, entry_id) DO NOTHING
                """,
                [(owner_id, node.entry_id, node.parent_id, seq, node.entry_json) for node in nodes],
            )
        return seq

    def get_raw_pi_thread(self, owner_id: str) -> RawPiThreadRow | None:
        """Return the per-session head, or ``None`` if the session is unknown."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT owner_id, session_id, session_file, leaf_id, latest_seq, updated_at
                FROM raw_pi_thread WHERE owner_id = ?
                """,
                (owner_id,),
            ).fetchone()
        if row is None:
            return None
        return RawPiThreadRow(
            owner_id=row[0],
            session_id=row[1],
            session_file=row[2],
            leaf_id=row[3],
            latest_seq=row[4],
            updated_at=row[5],
        )

    def get_raw_pi_thread_nodes(self, owner_id: str, *, include_abandoned: bool = False) -> RawPiThread:
        """Reconstruct the live branch, optionally with the abandoned branches.

        Live-only by default (walk from the head's ``leaf_id``); abandoned-fork
        nodes are excluded. Pass ``include_abandoned=True`` to also reconstruct
        each rewound branch (every other leaf) into ``abandoned`` — the optional
        "roads not taken", kept separate from the main thread. Returns empty
        ``live``/``abandoned`` when the session or its leaf is unknown.
        """

        with self._connect() as connection:
            head = connection.execute(
                "SELECT leaf_id FROM raw_pi_thread WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()
            if head is None or head[0] is None:
                return RawPiThread(live=[])

            live_leaf = head[0]
            live = _reconstruct_branch(connection, owner_id, live_leaf)
            if not include_abandoned:
                return RawPiThread(live=live)

            abandoned_leaves = connection.execute(
                """
                SELECT entry_id FROM raw_pi_thread_node
                WHERE owner_id = ?
                  AND entry_id != ?
                  AND entry_id NOT IN (
                      SELECT parent_id FROM raw_pi_thread_node
                      WHERE owner_id = ? AND parent_id IS NOT NULL
                  )
                ORDER BY first_seen_seq, entry_id
                """,
                (owner_id, live_leaf, owner_id),
            ).fetchall()
            abandoned = [_reconstruct_branch(connection, owner_id, leaf[0]) for leaf in abandoned_leaves]

        return RawPiThread(live=live, abandoned=abandoned)
