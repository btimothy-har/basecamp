"""Reads for the ``analysis`` table: the latest analyzer output per session."""

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


class AnalysisReaderMixin:
    """Latest-only ``analysis`` queries."""

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
