"""Writes for the ``analysis`` table: upsert the latest analyzer output."""

from __future__ import annotations


class AnalysisWriterMixin:
    """Latest-only ``analysis`` mutations."""

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
