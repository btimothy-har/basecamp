"""Work item refinement — turns classified WorkItems into TranscriptEvents.

LLM-driven stage that summarizes thinking blocks and tool pairs, creates
TranscriptEvents. Items are marked REFINED, TERMINAL, or ERROR.
"""

import json
import logging
from datetime import UTC, datetime

from observer.data.enums import WorkItemStage, WorkItemType
from observer.data.raw_event import RawEvent
from observer.data.transcript_event import TranscriptEvent
from observer.data.work_item import WorkItem
from observer.exceptions import ExtractionError
from observer.pipeline.llm import summarize_thinking, summarize_tool_pair
from observer.services.db import Database

logger = logging.getLogger(__name__)


class WorkItemRefiner:
    """Refines a batch of WorkItems for a single transcript."""

    @staticmethod
    def has_pending() -> bool:
        """Check if any WorkItems need refining (processed=0)."""
        return WorkItem.has_unprocessed()

    def __init__(self, db: Database, transcript_id: int):
        self._db = db
        self._transcript_id = transcript_id
        self._prompt_event_id: int | None = None

    def refine(self, items: list[WorkItem]) -> int:
        refined = 0
        for item in items:
            match item.item_type:
                case WorkItemType.PROMPT:
                    self._handle_prompt(item)
                case WorkItemType.THINKING:
                    self._handle_thinking(item)
                case WorkItemType.TOOL_PAIR:
                    self._handle_tool_pair(item)
                case WorkItemType.RESPONSE:
                    self._handle_response(item)
                case t if t.is_skipped:
                    self._handle_skipped(item)
            if item.processed == WorkItemStage.REFINED:
                refined += 1
        return refined

    def _handle_prompt(self, work_item: WorkItem) -> None:
        raw = RawEvent.get(work_item.event_ids[0])
        if raw is None:
            self._mark_work_item(work_item, WorkItemStage.ERROR)
            return

        user_text = raw.extract_user_text()
        if not user_text:
            self._mark_work_item(work_item, WorkItemStage.TERMINAL)
            return

        te = self._save_transcript_event(work_item, user_text)
        self._prompt_event_id = te.id
        self._mark_work_item(work_item, WorkItemStage.REFINED)

    def _handle_thinking(self, work_item: WorkItem) -> None:
        raw = RawEvent.get(work_item.event_ids[0])
        if raw is None:
            self._mark_work_item(work_item, WorkItemStage.ERROR)
            return

        thinking_text = raw.extract_thinking_text()
        if not thinking_text:
            self._mark_work_item(work_item, WorkItemStage.TERMINAL)
            return

        try:
            summary = summarize_thinking(thinking_text)
        except ExtractionError:
            logger.exception("Thinking summarization failed")
            self._mark_work_item(work_item, WorkItemStage.ERROR)
            return

        self._save_transcript_event(work_item, summary)
        self._mark_work_item(work_item, WorkItemStage.REFINED)

    def _handle_tool_pair(self, work_item: WorkItem) -> None:
        tool_use_raw = RawEvent.get(work_item.event_ids[0])
        tool_result_raw = RawEvent.get(work_item.event_ids[1])
        if tool_use_raw is None or tool_result_raw is None:
            self._mark_work_item(work_item, WorkItemStage.ERROR)
            return

        tool_name = tool_use_raw.get_tool_name() or "Unknown"
        tool_input = tool_use_raw.get_tool_input() or {}
        result_content = tool_result_raw.get_tool_result_content() or ""
        input_str = json.dumps(tool_input, indent=None, default=str)

        try:
            result = summarize_tool_pair(tool_name, input_str, result_content)
        except ExtractionError:
            logger.exception("Tool summarization failed")
            self._mark_work_item(work_item, WorkItemStage.ERROR)
            return

        self._save_transcript_event(work_item, result.summary)
        self._mark_work_item(work_item, WorkItemStage.REFINED)

    def _handle_response(self, work_item: WorkItem) -> None:
        raw = RawEvent.get(work_item.event_ids[0])
        if raw is None:
            self._mark_work_item(work_item, WorkItemStage.ERROR)
            return

        agent_text = raw.extract_agent_text()
        if not agent_text:
            self._mark_work_item(work_item, WorkItemStage.TERMINAL)
            return

        thinking_text = raw.extract_thinking_text()
        if thinking_text:
            try:
                embedded_thinking = summarize_thinking(thinking_text)
                self._save_transcript_event(work_item, embedded_thinking, event_type=WorkItemType.THINKING)
            except ExtractionError:
                logger.exception("Thinking summarization failed in response handler")

        self._save_transcript_event(work_item, agent_text)
        self._mark_work_item(work_item, WorkItemStage.REFINED)

    def _handle_skipped(self, work_item: WorkItem) -> None:
        self._mark_work_item(work_item, WorkItemStage.TERMINAL)

    def _save_transcript_event(
        self,
        work_item: WorkItem,
        text: str,
        *,
        event_type: WorkItemType | None = None,
    ) -> TranscriptEvent:
        te = TranscriptEvent(
            transcript_id=self._transcript_id,
            work_item_id=work_item.id,
            event_type=event_type or work_item.item_type,
            text=text,
            created_at=datetime.now(UTC),
        )
        with self._db.session() as session:
            te = te.save(session)
        return te

    def _mark_work_item(self, work_item: WorkItem, stage: WorkItemStage) -> None:
        work_item.processed = stage
        with self._db.session() as session:
            work_item.save(session)
