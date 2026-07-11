"""SQLite persistence for the companion analysis — latest-only per session.

The analysis is a pure derivative of the raw thread (the durable source of
truth), so it is stored as a persisted *cache*: one row per ``owner_id``,
upserted each run, not a versioned history. ``based_on_thread_seq`` records the
``raw_pi_thread.latest_seq`` the analysis read, so the scheduler can tell whether
a stored analysis is stale (see docs/design/companion-daemon-broker.md §5/§6.1).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisRow:
    """The latest analyzer output for one session."""

    owner_id: str
    based_on_thread_seq: int | None
    model: str | None
    sections_json: str
    updated_at: str


class AnalysisMixin:
    """Store mixin for the latest-only ``analysis`` table."""

    def record_analysis(
        self,
        *,
        owner_id: str,
        based_on_thread_seq: int | None,
        model: str | None,
        sections_json: str,
        now: str | None = None,
    ) -> None:
        """Upsert the latest analysis for a session (replaces any prior row)."""

        timestamp = now or self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO analysis (owner_id, based_on_thread_seq, model, sections_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(owner_id)
                DO UPDATE SET
                    based_on_thread_seq = excluded.based_on_thread_seq,
                    model = excluded.model,
                    sections_json = excluded.sections_json,
                    updated_at = excluded.updated_at
                """,
                (owner_id, based_on_thread_seq, model, sections_json, timestamp),
            )

    def get_analysis(self, owner_id: str) -> AnalysisRow | None:
        """Return the latest analysis for a session, or ``None`` if none exists."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT owner_id, based_on_thread_seq, model, sections_json, updated_at
                FROM analysis WHERE owner_id = ?
                """,
                (owner_id,),
            ).fetchone()
        if row is None:
            return None
        return AnalysisRow(
            owner_id=row[0],
            based_on_thread_seq=row[1],
            model=row[2],
            sections_json=row[3],
            updated_at=row[4],
        )
