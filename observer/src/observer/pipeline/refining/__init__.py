"""Event refining — refines classified work items into transcript events.

WorkItem(UNREFINED) → TranscriptEvent, mark REFINED/TERMINAL/ERROR

Refinement involves LLM calls for thinking/tool_pair summarization.
Grouping (RawEvent → WorkItem) is handled by ingest, not here.
"""

import logging

from observer.data.work_item import WorkItem
from observer.pipeline.refining.refinement import WorkItemRefiner
from observer.services.db import Database

logger = logging.getLogger(__name__)


class EventRefiner:
    """Refines classified WorkItems into TranscriptEvents."""

    @staticmethod
    def refine_pending(db: Database, *, transcript_id: int | None = None) -> int:
        """Refine unprocessed WorkItems into TranscriptEvents.

        Assumes grouping has already been done (by ingest). Returns the
        number of WorkItems refined.
        """
        items = WorkItem.claim_unprocessed(transcript_id=transcript_id)
        if not items:
            return 0

        logger.info("Refining %d unprocessed work items", len(items))

        refiner = WorkItemRefiner(db)
        total = refiner.refine(items)

        logger.info("Refining complete: %d work items refined", total)
        return total
