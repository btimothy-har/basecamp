"""Event grouping — classifies raw events into typed work items.

Pure classification logic with no LLM calls. Handles tool_use/tool_result
pairing, type mapping, and skip-tool filtering. Persists WorkItems and
marks RawEvents as processed.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from observer.constants import DEFAULT_STALE_THRESHOLD
from observer.data.enums import RawEventStatus, WorkItemType
from observer.data.raw_event import RawEvent
from observer.data.work_item import WorkItem
from observer.services.db import Database

logger = logging.getLogger(__name__)

# Tool names that produce no meaningful transcript events (task management noise)
SKIP_TOOLS = frozenset({"TaskCreate", "TaskUpdate", "TaskList", "TaskGet"})


@dataclass(frozen=True, slots=True)
class ClassifiedItem:
    """Classification result — maps events to a WorkItem type."""

    item_type: WorkItemType
    events: list[RawEvent] = field(default_factory=list)


def classify_events(events: list[RawEvent]) -> list[ClassifiedItem]:
    """Classify raw events into typed items.

    Pure classification with no side effects. Handles tool_use/tool_result
    pairing, including parallel tool calls where multiple tool_use events
    precede their corresponding tool_results.

    Trailing unmatched tool_uses are excluded (left unprocessed) so the
    next batch can pair them with their tool_results.
    """
    items: list[ClassifiedItem] = []
    # tool_use ID → RawEvent, supports parallel tool calls
    pending_tool_uses: dict[str, RawEvent] = {}

    for event in events:
        if event.is_user_prompt():
            items.append(ClassifiedItem(WorkItemType.PROMPT, [event]))

        elif event.is_tool_use():
            if event.get_tool_name() in SKIP_TOOLS:
                items.append(ClassifiedItem(WorkItemType.TASK_MANAGEMENT, [event]))
            else:
                for tool_id in event.get_tool_use_ids():
                    pending_tool_uses[tool_id] = event

        elif event.is_tool_result():
            matched = False
            for result_id in event.get_tool_result_ids():
                if result_id in pending_tool_uses:
                    use_event = pending_tool_uses.pop(result_id)
                    items.append(ClassifiedItem(WorkItemType.TOOL_PAIR, [use_event, event]))
                    matched = True
                    break
            if not matched:
                items.append(ClassifiedItem(WorkItemType.ORPHANED_RESULT, [event]))

        elif event.is_thinking():
            if event.extract_thinking_text():
                items.append(ClassifiedItem(WorkItemType.THINKING, [event]))
            else:
                items.append(ClassifiedItem(WorkItemType.EMPTY_CONTENT, [event]))

        elif event.is_agent_text():
            if event.extract_agent_text():
                items.append(ClassifiedItem(WorkItemType.RESPONSE, [event]))
            else:
                items.append(ClassifiedItem(WorkItemType.EMPTY_CONTENT, [event]))

        else:
            items.append(ClassifiedItem(WorkItemType.UNRECOGNIZED, [event]))

    # Trailing unmatched tool_uses: don't emit — leave at processed=0
    # so the next batch picks them up and pairs with their tool_results.

    return items


class EventGrouper:
    """Groups ungrouped RawEvents into classified WorkItems."""

    @staticmethod
    def has_pending() -> bool:
        """Check if any RawEvents need grouping (processed=0)."""
        return RawEvent.has_unprocessed()

    @staticmethod
    def group_batch(db: Database, *, batch_limit: int) -> int:
        """Classify ungrouped RawEvents into WorkItems. Returns count created."""
        events = RawEvent.get_unprocessed(limit=batch_limit)
        if not events:
            return 0

        logger.info("Classifying %d ungrouped events", len(events))

        groups: dict[int, list[RawEvent]] = {}
        for event in events:
            groups.setdefault(event.transcript_id, []).append(event)

        total = 0
        for transcript_id, transcript_events in groups.items():
            classified = classify_events(transcript_events)
            now = datetime.now(UTC)

            # Find events not included in any classified item (e.g. trailing
            # unmatched tool_uses). Only mark them SKIPPED once they're older
            # than the stale threshold — recent ones may still get a matching
            # tool_result in the next batch.
            classified_event_ids = {e.id for item in classified for e in item.events}
            stale_cutoff = now.replace(tzinfo=None) - timedelta(seconds=DEFAULT_STALE_THRESHOLD)
            orphaned = [
                e
                for e in transcript_events
                if e.id not in classified_event_ids and e.timestamp.replace(tzinfo=None) < stale_cutoff
            ]

            with db.session() as session:
                for item in classified:
                    work_item = WorkItem(
                        transcript_id=transcript_id,
                        item_type=item.item_type,
                        event_ids=[e.id for e in item.events],
                        created_at=now,
                    )
                    work_item.save(session)

                    for event in item.events:
                        event.processed = RawEventStatus.PROCESSED
                        event.save(session)

                for event in orphaned:
                    event.processed = RawEventStatus.SKIPPED
                    event.save(session)

            total += len(classified)

        logger.info("Classification complete: %d work items created", total)
        return total
