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


def _fetch_owner_nodes(
    connection: sqlite3.Connection, owner_id: str
) -> tuple[dict[str, tuple[str | None, str]], list[str], set[str]]:
    """Load one owner's nodes once: ``(node_map, entry_ids_in_order, referenced_parents)``.

    ``node_map`` maps ``entry_id -> (parent_id, entry_json)``; ``entry_ids_in_order`` is
    ``(first_seen_seq, entry_id)`` ordered (for stable abandoned-leaf ordering); and
    ``referenced_parents`` is the set of ids used as a parent (non-leaf nodes).
    """

    rows = connection.execute(
        """
        SELECT entry_id, parent_id, entry_json, first_seen_seq
        FROM raw_pi_thread_node WHERE owner_id = ?
        ORDER BY first_seen_seq, entry_id
        """,
        (owner_id,),
    ).fetchall()
    node_map = {row[0]: (row[1], row[2]) for row in rows}
    ordered = [row[0] for row in rows]
    referenced_parents = {row[1] for row in rows if row[1] is not None}
    return node_map, ordered, referenced_parents


def _reconstruct_branch(node_map: dict[str, tuple[str | None, str]], leaf_id: str) -> list[str]:
    """Walk ``parent_id`` up from ``leaf_id``, returning ``entry_json`` root→leaf.

    Cycle-safe: a ``visited`` set stops the walk the moment a parent link revisits an
    ancestor (a malformed/opaque cycle), so reconstruction is O(branch length) with no
    depth cap and never re-expands a loop.
    """

    chain: list[str] = []
    visited: set[str] = set()
    current: str | None = leaf_id
    while current is not None and current in node_map and current not in visited:
        visited.add(current)
        parent_id, entry_json = node_map[current]
        chain.append(entry_json)
        current = parent_id
    chain.reverse()
    return chain


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
        """Insert only new nodes and advance the head seq only when the branch changed.

        The seq is the analyzer's freshness cursor, so it must advance only on a real
        change — new nodes inserted or the leaf moved. A duplicate/replayed report that
        adds nothing keeps the prior seq, so it never triggers a redundant analysis run.
        """

        timestamp = now or self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT latest_seq, leaf_id FROM raw_pi_thread WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()
            prior_seq = row[0] if row is not None else 0
            prior_leaf = row[1] if row is not None else None
            new_seq = prior_seq + 1

            changes_before = connection.total_changes
            connection.executemany(
                """
                INSERT INTO raw_pi_thread_node (owner_id, entry_id, parent_id, first_seen_seq, entry_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(owner_id, entry_id) DO NOTHING
                """,
                [(owner_id, node.entry_id, node.parent_id, new_seq, node.entry_json) for node in nodes],
            )
            inserted = connection.total_changes - changes_before
            changed = row is None or inserted > 0 or leaf_id != prior_leaf
            seq = new_seq if changed else prior_seq

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
            node_map, ordered, referenced_parents = _fetch_owner_nodes(connection, owner_id)
            live = _reconstruct_branch(node_map, live_leaf)
            if not include_abandoned:
                return RawPiThread(live=live)

            # Abandoned leaves: nodes that are no one's parent, other than the live leaf.
            abandoned_leaves = [
                entry_id for entry_id in ordered if entry_id != live_leaf and entry_id not in referenced_parents
            ]
            abandoned = [_reconstruct_branch(node_map, leaf) for leaf in abandoned_leaves]

        return RawPiThread(live=live, abandoned=abandoned)
