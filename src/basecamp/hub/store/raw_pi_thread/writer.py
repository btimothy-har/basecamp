"""Writes for the raw pi thread: the node input type and the insert-only ingest."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RawPiThreadNode:
    """One thread entry to persist; ``entry_json`` is stored verbatim."""

    entry_id: str
    parent_id: str | None
    entry_json: str


class RawPiThreadWriterMixin:
    """Insert-only ingest of a session's raw thread nodes."""

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
        with self._writing(immediate=True) as connection:
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
