"""Event refining — refines classified work items into transcript events.

WorkItem(UNREFINED) → TranscriptEvent, mark REFINED/TERMINAL/ERROR

Refinement involves LLM calls for thinking/tool_pair summarization.
Grouping (RawEvent → WorkItem) is handled by ingest, not here.
"""

import logging

from observer.data.enums import WorkItemStage
from observer.data.work_item import WorkItem
from observer.pipeline.refining.refinement import WorkItemRefiner
from observer.services.db import Database

logger = logging.getLogger(__name__)


def _reset_incomplete(db: Database, items: list[WorkItem]) -> None:
    """Reset any items still in REFINING state back to UNREFINED."""
    incomplete = [i for i in items if i.processed == WorkItemStage.REFINING]
    if not incomplete:
        return
    logger.info("Resetting %d incomplete REFINING items to UNREFINED", len(incomplete))
    with db.session() as session:
        for item in incomplete:
            item.processed = WorkItemStage.UNREFINED
            item.claimed_at = None
            item.save(session)


class EventRefiner:
    """Refines classified WorkItems into TranscriptEvents."""

    @staticmethod
    def refine_pending(db: Database, *, transcript_id: int | None = None) -> int:
        """Refine unprocessed WorkItems into TranscriptEvents.

        Recovers stale REFINING items from crashed runs, then claims and
        refines pending work items.
        """
        WorkItem.recover_stale()

        items = WorkItem.claim_unprocessed(transcript_id=transcript_id)
        if not items:
            return 0

        logger.info("Refining %d unprocessed work items", len(items))

        refiner = WorkItemRefiner(db)
        total = refiner.refine(items)
        _reset_incomplete(db, items)

        logger.info("Refining complete: %d work items refined", total)
        return total
