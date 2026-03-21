"""Transcript extraction — produces structured sections from refined events.

Operates on transcripts that have TranscriptEvents (created by the refine stage).
Single LLM call per transcript produces all section types at once.
"""

import logging
from datetime import UTC, datetime

from observer.data.artifact import Artifact
from observer.data.enums import SectionType, WorkItemType
from observer.data.transcript_event import TranscriptEvent
from observer.exceptions import ExtractionError
from observer.pipeline.llm import extract_sections
from observer.services.db import Database

logger = logging.getLogger(__name__)

# Section fields on the LLM result mapped to SectionType enum values
_SECTION_FIELDS: list[tuple[str, SectionType]] = [
    ("summary", SectionType.SUMMARY),
    ("knowledge", SectionType.KNOWLEDGE),
    ("decisions", SectionType.DECISIONS),
    ("constraints", SectionType.CONSTRAINTS),
    ("actions", SectionType.ACTIONS),
]


class TranscriptExtractor:
    """Extracts structured sections from a complete transcript."""

    @staticmethod
    def extract_transcript(db: Database, transcript_id: int) -> int:
        """Extract sections for a transcript. Returns count of sections created."""
        events = TranscriptEvent.get_for_transcript(transcript_id)
        event_texts = [
            e.text
            for e in events
            if e.event_type != WorkItemType.THINKING and not e.event_type.is_skipped
        ]

        if not event_texts:
            return 0

        try:
            result = extract_sections(event_texts)
        except ExtractionError:
            logger.exception("Extraction failed for transcript %d", transcript_id)
            return 0

        now = datetime.now(UTC)
        count = 0
        with db.session() as session:
            for field_name, section_type in _SECTION_FIELDS:
                text = getattr(result, field_name)
                if not text:
                    continue

                if section_type == SectionType.SUMMARY:
                    text = f"## {result.title}\n{text}"

                artifact = Artifact(
                    transcript_id=transcript_id,
                    section_type=section_type,
                    text=text,
                    created_at=now,
                    updated_at=now,
                )
                artifact.save(session)
                count += 1

        logger.info(
            "Extracted %d sections for transcript %d",
            count,
            transcript_id,
        )
        return count
