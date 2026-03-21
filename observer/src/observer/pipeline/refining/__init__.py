"""Event refining — classifies raw events into work items, then refines them.

Two-phase stage:
  1. Group: RawEvent(PENDING) → WorkItem(UNREFINED)
  2. Refine: WorkItem(UNREFINED) → TranscriptEvent, mark REFINED/TERMINAL/ERROR

Grouping is pure logic (tool_use/tool_result pairing, type mapping).
Refinement involves LLM calls for thinking/tool_pair summarization.
"""

import logging

from observer.constants import REFINING_BATCH_LIMIT
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
    def refine_batch(db: Database, *, batch_limit: int = REFINING_BATCH_LIMIT) -> int:
        """Group ungrouped RawEvents, then refine unprocessed WorkItems.

        Returns the number of WorkItems refined.
        """
        # Phase 1: Group ungrouped raw events into work items
        EventGrouper.group_batch(db, batch_limit=batch_limit)

        # Phase 2: Refine unprocessed work items
        items = WorkItem.get_unprocessed(limit=batch_limit)
        if not items:
            return 0

        logger.info("Refining %d unprocessed work items", len(items))

        groups: dict[int, list[WorkItem]] = {}
        for item in items:
            groups.setdefault(item.transcript_id, []).append(item)

        total = 0
        for transcript_id, transcript_items in groups.items():
            refiner = WorkItemRefiner(db, transcript_id)
            total += refiner.refine(transcript_items)

        logger.info("Refining batch complete: %d work items refined", total)
        return total
