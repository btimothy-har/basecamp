"""Lightweight transcript summarization — works directly from raw events.

Used in lite mode (extraction disabled) to generate transcript summaries
without running the full Group → Refine → Extract pipeline. Produces one
LLM call per transcript summary refresh instead of per-event LLM calls.
"""

import logging
from datetime import UTC, datetime

from observer.constants import SUMMARY_INTERVAL
from observer.data.raw_event import RawEvent
from observer.data.schemas import RawEventSchema, TranscriptSchema
from observer.pipeline.extraction import extract_title
from observer.pipeline.llm import summarize_transcript
from observer.services.db import Database

logger = logging.getLogger(__name__)


def has_pending(db: Database | None = None) -> bool:
    """Check if any active transcripts need a summary refresh.

    A transcript needs refresh when it has ingested raw events and either
    has never been summarized or the cooldown has elapsed.
    """
    now = datetime.now(UTC)
    with (db or Database()).session() as session:
        transcripts = session.query(TranscriptSchema).filter(TranscriptSchema.ended_at.is_(None)).all()
        for t in transcripts:
            # Must have ingested events
            has_events = (
                session.query(RawEventSchema.id).filter(RawEventSchema.transcript_id == t.id).limit(1).first()
            ) is not None
            if not has_events:
                continue

            if t.last_summary_at is None:
                return True

            elapsed = (now - t.last_summary_at.replace(tzinfo=UTC)).total_seconds()
            if elapsed >= SUMMARY_INTERVAL:
                return True

    return False


def summarize_active_transcripts(db: Database) -> int:
    """Summarize active transcripts from raw events. Returns count updated."""
    now = datetime.now(UTC)
    updated = 0

    with db.session() as session:
        transcripts = (
            session.query(TranscriptSchema)
            .filter(
                TranscriptSchema.ended_at.is_(None),
                session.query(RawEventSchema.id).filter(RawEventSchema.transcript_id == TranscriptSchema.id).exists(),
            )
            .all()
        )
        # Collect IDs before closing session — we only need id + last_summary_at
        pending = []
        for t in transcripts:
            if t.last_summary_at is not None:
                elapsed = (now - t.last_summary_at.replace(tzinfo=UTC)).total_seconds()
                if elapsed < SUMMARY_INTERVAL:
                    continue
            pending.append(t.id)

    for transcript_id in pending:
        if _summarize_transcript(db, transcript_id):
            updated += 1

    if updated:
        logger.info("Summarized %d transcripts (lite mode)", updated)
    return updated


def _summarize_transcript(db: Database, transcript_id: int) -> bool:
    """Generate summary for a single transcript from raw events."""
    now = datetime.now(UTC)

    # Read extractable raw events (user prompts + assistant text)
    raw_events = RawEvent.get_for_transcript_summarizable(transcript_id)
    if not raw_events:
        return False

    texts = [e.format() for e in raw_events]

    try:
        summary = summarize_transcript(texts)
    except Exception:
        logger.exception("Summary generation failed for transcript %d", transcript_id)
        return False

    title = extract_title(summary)

    with db.session() as session:
        row = session.get(TranscriptSchema, transcript_id)
        if row is None:
            return False
        row.summary = summary
        row.title = title
        row.last_summary_at = now

    return True
