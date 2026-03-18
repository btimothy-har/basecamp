"""Work item extraction — Extract + Summarize pipeline.

Operates on refined WorkItems (REFINED stage) that already have TranscriptEvents.

Phase 1 (Extract): Batch call extracts artifacts from transcript event texts.
Phase 2 (Summarize): Regenerates summary if SUMMARY_INTERVAL has elapsed since last update.

Thinking events are excluded from both extraction and summary inputs.
Extraction is skipped when the only new events are prompts (no tool/response activity).
"""

import logging
from datetime import UTC, datetime

from observer.constants import EXTRACTION_BATCH_LIMIT, SUMMARY_INTERVAL
from observer.data.enums import ArtifactSource, WorkItemStage, WorkItemType
from observer.data.schemas import ArtifactSchema, TranscriptEventSchema, TranscriptSchema
from observer.data.transcript_event import TranscriptEvent
from observer.data.work_item import WorkItem
from observer.exceptions import ExtractionError
from observer.pipeline.llm import extract_artifacts, summarize_transcript
from observer.services.db import Database

logger = logging.getLogger(__name__)

_TITLE_MAX_LEN = 50


def _extract_title(summary: str) -> str | None:
    """Extract the first content line after '## Title' from a structured summary."""
    in_title = False
    for line in summary.splitlines():
        if line.strip() == "## Title":
            in_title = True
            continue
        if in_title:
            stripped = line.strip()
            if stripped.startswith("## "):
                return None
            if stripped:
                return stripped[:_TITLE_MAX_LEN]
    return None


# WorkItem types that represent real activity (non-prompt work)
_ACTIVITY_TYPES = frozenset({WorkItemType.TOOL_PAIR, WorkItemType.RESPONSE})


class WorkItemExtractor:
    """Extracts artifacts from refined WorkItems."""

    @classmethod
    def extract_batch(cls, db: Database, *, batch_limit: int = EXTRACTION_BATCH_LIMIT) -> int:
        """Extract artifacts from a batch of refined WorkItems. Returns artifact count."""
        items = WorkItem.get_by_processed(WorkItemStage.REFINED, limit=batch_limit)
        if not items:
            return 0

        logger.info("Extracting %d refined work items", len(items))

        groups: dict[int, list[WorkItem]] = {}
        for item in items:
            groups.setdefault(item.transcript_id, []).append(item)

        total = 0
        for transcript_id, transcript_items in groups.items():
            with db.session() as session:
                transcript_row = session.get(TranscriptSchema, transcript_id)
                initial_summary = (transcript_row.summary or "") if transcript_row else ""

            total += _process_transcript(db, transcript_id, transcript_items, initial_summary)

        logger.info("Extraction batch complete: %d artifacts created", total)
        return total

    @classmethod
    def has_pending(cls) -> bool:
        """Check if any refined WorkItems need processing."""
        return WorkItem.has_by_processed(WorkItemStage.REFINED)


def _process_transcript(
    db: Database,
    transcript_id: int,
    items: list[WorkItem],
    initial_summary: str,
) -> int:
    """Extract artifacts from a set of refined WorkItems. Thinking events are excluded."""
    # Derive state from DB — TranscriptEvents already created by Refine stage
    item_ids = [item.id for item in items]
    with db.session() as session:
        te_rows = (
            session.query(TranscriptEventSchema)
            .filter(TranscriptEventSchema.work_item_id.in_(item_ids))
            .order_by(TranscriptEventSchema.created_at)
            .all()
        )
        new_event_texts = [row.text for row in te_rows if row.event_type != WorkItemType.THINKING]
        last_event_id = te_rows[-1].id if te_rows else None

    if not te_rows:
        logger.warning(
            "Refined items for transcript %d have no TranscriptEvents; marking ERROR",
            transcript_id,
        )
        with db.session() as session:
            for item in items:
                item.processed = WorkItemStage.ERROR
                item.save(session)
        return 0

    if not new_event_texts:
        # All events were thinking-only — nothing to extract, mark terminal
        with db.session() as session:
            for item in items:
                item.processed = WorkItemStage.TERMINAL
                item.save(session)
        return 0

    # Derive prompt_event_id from the first PROMPT item's TranscriptEvent
    prompt_event_id: int | None = None
    prompt_items = [i for i in items if i.item_type == WorkItemType.PROMPT]
    if prompt_items:
        with db.session() as session:
            prompt_te = (
                session.query(TranscriptEventSchema)
                .filter(TranscriptEventSchema.work_item_id == prompt_items[0].id)
                .first()
            )
            if prompt_te:
                prompt_event_id = prompt_te.id

    has_activity = any(item.item_type in _ACTIVITY_TYPES for item in items)

    # Phase 1: Extract artifacts from new events (skip if only prompts)
    artifact_count = 0
    if has_activity:
        try:
            artifact_count = _extract_batch(
                db,
                transcript_id,
                initial_summary,
                new_event_texts,
                last_event_id=last_event_id,
                prompt_event_id=prompt_event_id,
            )
        except ExtractionError:
            logger.exception("Extraction failed for transcript %d", transcript_id)
            with db.session() as session:
                for item in items:
                    item.processed = WorkItemStage.ERROR
                    item.save(session)
            return 0

    # Phase 2: Regenerate summary if cooldown has elapsed
    _update_summary(db, transcript_id)

    # Mark all items as terminal
    with db.session() as session:
        for item in items:
            item.processed = WorkItemStage.TERMINAL
            item.save(session)

    return artifact_count


def _extract_batch(
    db: Database,
    transcript_id: int,
    summary: str,
    event_texts: list[str],
    *,
    last_event_id: int | None,
    prompt_event_id: int | None,
) -> int:
    """Extract artifacts from transcript event texts. Returns count created."""
    result = extract_artifacts(summary, event_texts)

    count = 0
    now = datetime.now(UTC)
    with db.session() as session:
        for extracted in result.artifacts:
            artifact = ArtifactSchema(
                artifact_type=extracted.artifact_type,
                origin=ArtifactSource.EXTRACTED.value,
                text=extracted.text,
                transcript_id=transcript_id,
                transcript_event_id=last_event_id,
                prompt_event_id=prompt_event_id,
                source=extracted.source,
                created_at=now,
            )
            session.add(artifact)
            session.flush()
            count += 1

    return count


def _update_summary(db: Database, transcript_id: int) -> None:
    """Regenerate transcript summary if SUMMARY_INTERVAL has elapsed since last update."""
    now = datetime.now(UTC)

    with db.session() as session:
        transcript_row = session.get(TranscriptSchema, transcript_id)
        if transcript_row is None:
            return
        if transcript_row.last_summary_at is not None:
            elapsed = (now - transcript_row.last_summary_at.replace(tzinfo=UTC)).total_seconds()
            if elapsed < SUMMARY_INTERVAL:
                return

    try:
        all_events = TranscriptEvent.get_for_transcript(transcript_id)
        all_texts = [te.text for te in all_events if te.event_type != WorkItemType.THINKING]

        if not all_texts:
            return

        new_summary = summarize_transcript(all_texts)

        title = _extract_title(new_summary)
        with db.session() as session:
            transcript_row = session.get(TranscriptSchema, transcript_id)
            if transcript_row is not None:
                transcript_row.summary = new_summary
                transcript_row.title = title
                transcript_row.last_summary_at = now
    except ExtractionError:
        logger.exception("Summary generation failed for transcript %d", transcript_id)
