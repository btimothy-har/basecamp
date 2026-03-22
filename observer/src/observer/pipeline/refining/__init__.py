"""Event refining — classifies raw events into work items, then refines them.

Two-phase stage:
  1. Group: RawEvent(PENDING) → WorkItem(UNREFINED)
  2. Refine: WorkItem(UNREFINED) → TranscriptEvent, mark REFINED/TERMINAL/ERROR

Grouping is pure logic (tool_use/tool_result pairing, type mapping).
Refinement involves LLM calls for thinking/tool_pair summarization.
"""

import logging

from observer.data.work_item import WorkItem
from observer.pipeline.refining.grouping import EventGrouper
from observer.pipeline.refining.refinement import WorkItemRefiner
from observer.services.db import Database

logger = logging.getLogger(__name__)


class EventRefiner:
    """Coordinates grouping and refinement of raw events.

    Thin orchestrator that runs both phases in sequence:
      1. EventGrouper: ungrouped RawEvents → WorkItems
      2. WorkItemRefiner: WorkItems → TranscriptEvents
    """

    @staticmethod
    def refine_pending(db: Database, *, transcript_id: int | None = None) -> int:
        """Group ungrouped RawEvents, then refine unprocessed WorkItems.

        Returns the number of WorkItems refined.
        """
        # Phase 1: Group ungrouped raw events into work items
        EventGrouper.group_pending(db, transcript_id=transcript_id)

        # Phase 2: Atomically claim unprocessed work items, then refine
        items = WorkItem.claim_unprocessed(transcript_id=transcript_id)
        if not items:
            return 0

        logger.info("Refining %d unprocessed work items", len(items))

        refiner = WorkItemRefiner(db)
        total = refiner.refine(items)

        logger.info("Refining complete: %d work items refined", total)
        return total
