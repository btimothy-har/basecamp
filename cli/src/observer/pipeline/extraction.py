"""Transcript extraction — produces structured sections from refined events.

Operates on transcripts that have TranscriptEvents (created by the refine stage).
Single LLM call per transcript produces all section types at once.
"""

import asyncio
import logging
from datetime import UTC, datetime

from observer.data.artifact import Artifact
from observer.data.enums import SectionType, WorkItemType
from observer.data.schemas import ArtifactSchema
from observer.data.transcript_event import TranscriptEvent
from observer.llm import agents
from observer.llm.agents import ExtractionResult
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


async def _extract_sections(event_texts: list[str]) -> ExtractionResult:
    """Extract structured sections from transcript event texts."""
    event_list = "\n".join(f"{i + 1}. {e}" for i, e in enumerate(event_texts))
    prompt = f"## Transcript Events\n{event_list}"

    try:
        result = await agents.section_extractor.run(prompt)
    except Exception:
        logger.warning("Extraction failed, returning fallback", exc_info=True)
        return ExtractionResult(
            title="Untitled session",
            summary="",
            knowledge="",
            decisions="",
            constraints="",
            actions="",
        )
    return result.output


class TranscriptExtractor:
    """Extracts structured sections from a complete transcript."""

    @staticmethod
    def extract_transcript(db: Database, transcript_id: int) -> int:
        """Extract sections for a transcript. Returns count of sections created."""
        events = TranscriptEvent.get_for_transcript(transcript_id)
        event_texts = [e.text for e in events if e.event_type != WorkItemType.THINKING and not e.event_type.is_skipped]

        if not event_texts:
            return 0

        result = asyncio.run(_extract_sections(event_texts))

        now = datetime.now(UTC)
        count = 0
        emitted: set[SectionType] = set()
        with db.session() as session:
            for field_name, section_type in _SECTION_FIELDS:
                text = getattr(result, field_name)
                if not text or not text.strip():
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
                emitted.add(section_type)
                count += 1

            # Remove stale sections from prior extractions
            if emitted:
                all_types = {st for _, st in _SECTION_FIELDS}
                stale_types = all_types - emitted
                if stale_types:
                    session.query(ArtifactSchema).filter(
                        ArtifactSchema.transcript_id == transcript_id,
                        ArtifactSchema.section_type.in_(stale_types),
                    ).delete(synchronize_session="fetch")

        logger.info(
            "Extracted %d sections for transcript %d",
            count,
            transcript_id,
        )
        return count
