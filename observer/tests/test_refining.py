"""Tests for the event refining pipeline stage (classify + refine)."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from observer.data.enums import ArtifactType, RawEventStatus, WorkItemStage, WorkItemType
from observer.data.raw_event import RawEvent
from observer.data.schemas import ArtifactSchema, ProjectSchema, RawEventSchema, TranscriptEventSchema, TranscriptSchema
from observer.data.work_item import WorkItem
from observer.exceptions import ExtractionError
from observer.pipeline.models import ToolSummaryResult
from observer.pipeline.refining import EventRefiner
from observer.pipeline.refining.grouping import EventGrouper, classify_events
from observer.pipeline.refining.refinement import WorkItemRefiner

NOW = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)


def _ts(minute: int = 0) -> datetime:
    return NOW.replace(minute=minute)


def _make_raw_event(
    event_type: str = "user",
    content: dict | None = None,
    **kwargs,
) -> RawEvent:
    """Build a RawEvent with JSON content."""
    if content is None:
        content = {
            "type": event_type,
            "message": {"role": event_type, "content": "x" * 60},
        }
    return RawEvent(
        id=kwargs.get("id", 1),
        transcript_id=kwargs.get("transcript_id", 1),
        event_type=event_type,
        timestamp=kwargs.get("timestamp", NOW),
        content=json.dumps(content),
        processed=RawEventStatus.PENDING,
    )


def _user_text_event(text: str = "x" * 60, **kwargs) -> RawEvent:
    return _make_raw_event(
        "user",
        {"type": "user", "message": {"role": "user", "content": text}},
        **kwargs,
    )


def _assistant_event(text: str = "x" * 60, **kwargs) -> RawEvent:
    return _make_raw_event(
        "assistant",
        {"type": "assistant", "message": {"role": "assistant", "content": text}},
        **kwargs,
    )


def _tool_use_event(
    name: str = "Read",
    tool_id: str = "tu-1",
    tool_input: dict | None = None,
    **kwargs,
) -> RawEvent:
    """Assistant event with a tool_use block."""
    return _make_raw_event(
        "assistant",
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": name,
                        "input": tool_input or {"file_path": "/src/auth.py"},
                    }
                ],
            },
        },
        **kwargs,
    )


def _tool_result_event(tool_id: str = "tu-1", content: str = "ok", **kwargs) -> RawEvent:
    """User event with a tool_result block."""
    return _make_raw_event(
        "user",
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": content}],
            },
        },
        **kwargs,
    )


def _thinking_event(text: str = "x" * 60, **kwargs) -> RawEvent:
    return _make_raw_event(
        "assistant",
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": text, "signature": "sig-1"},
                ],
            },
        },
        **kwargs,
    )


def _progress_event(**kwargs) -> RawEvent:
    return _make_raw_event(
        "progress",
        {"type": "progress", "message": {"content": "hook running"}},
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Unit tests — classification logic (no DB)
# ---------------------------------------------------------------------------


class TestClassifyEvents:
    def test_user_prompt(self):
        event = _user_text_event("help me implement JWT authentication for the entire API system")
        items = classify_events([event])
        assert len(items) == 1
        assert items[0].item_type == WorkItemType.PROMPT
        assert items[0].events == [event]

    def test_tool_pair(self):
        tu = _tool_use_event("Read", "tu-1")
        tr = _tool_result_event("tu-1", "file contents")
        items = classify_events([tu, tr])
        assert len(items) == 1
        assert items[0].item_type == WorkItemType.TOOL_PAIR
        assert items[0].events == [tu, tr]

    def test_agent_text(self):
        event = _assistant_event("I found the authentication module and here's what I see")
        items = classify_events([event])
        assert len(items) == 1
        assert items[0].item_type == WorkItemType.RESPONSE

    def test_thinking(self):
        event = _thinking_event("considering architecture options for the module")
        items = classify_events([event])
        assert len(items) == 1
        assert items[0].item_type == WorkItemType.THINKING

    def test_non_extractable_unrecognized(self):
        event = _progress_event()
        items = classify_events([event])
        assert len(items) == 1
        assert items[0].item_type == WorkItemType.UNRECOGNIZED

    def test_short_assistant_classified_as_response(self):
        event = _assistant_event("ok")
        items = classify_events([event])
        assert len(items) == 1
        assert items[0].item_type == WorkItemType.RESPONSE

    def test_parallel_tool_uses_paired_by_id(self):
        """Multiple tool_uses followed by results — paired by ID."""
        tu1 = _tool_use_event("Read", "tu-1")
        tu2 = _tool_use_event("Grep", "tu-2")
        tr1 = _tool_result_event("tu-1", "file content")
        tr2 = _tool_result_event("tu-2", "matches")
        items = classify_events([tu1, tu2, tr1, tr2])
        assert len(items) == 2
        assert items[0].item_type == WorkItemType.TOOL_PAIR
        assert items[0].events == [tu1, tr1]
        assert items[1].item_type == WorkItemType.TOOL_PAIR
        assert items[1].events == [tu2, tr2]

    def test_unmatched_parallel_tool_use_excluded(self):
        """Parallel tool_uses where only one gets a result — other stays pending."""
        tu1 = _tool_use_event("Read", "tu-1")
        tu2 = _tool_use_event("Grep", "tu-2")
        tr2 = _tool_result_event("tu-2", "matches")
        items = classify_events([tu1, tu2, tr2])
        assert len(items) == 1
        assert items[0].item_type == WorkItemType.TOOL_PAIR
        assert items[0].events == [tu2, tr2]

    def test_trailing_unmatched_tool_use_excluded(self):
        """Trailing tool_use is excluded so next batch can pair it."""
        tu = _tool_use_event("Read", "tu-1")
        items = classify_events([tu])
        assert len(items) == 0

    def test_tool_result_without_pending_orphaned(self):
        tr = _tool_result_event("tu-1", "content")
        items = classify_events([tr])
        assert len(items) == 1
        assert items[0].item_type == WorkItemType.ORPHANED_RESULT

    def test_skip_tools_classified_as_task_management(self):
        for tool_name in ("TaskCreate", "TaskUpdate", "TaskList", "TaskGet"):
            event = _tool_use_event(tool_name, "tu-skip")
            items = classify_events([event])
            assert len(items) == 1
            assert items[0].item_type == WorkItemType.TASK_MANAGEMENT

    def test_skip_tool_does_not_hold_pending(self):
        """Skip tool followed by tool_result — result becomes orphaned (no pending)."""
        tu = _tool_use_event("TaskCreate", "tu-1")
        tr = _tool_result_event("tu-1", "ok")
        items = classify_events([tu, tr])
        assert len(items) == 2
        assert items[0].item_type == WorkItemType.TASK_MANAGEMENT
        assert items[1].item_type == WorkItemType.ORPHANED_RESULT

    def test_pending_tool_use_survives_prompt(self):
        """Unmatched tool_use stays pending when a prompt arrives."""
        tu = _tool_use_event("Read", "tu-1")
        prompt = _user_text_event("help me implement JWT authentication for the entire API system")
        items = classify_events([tu, prompt])
        assert len(items) == 1
        assert items[0].item_type == WorkItemType.PROMPT

    def test_empty_thinking_classified_as_empty_content(self):
        event = _thinking_event("")
        items = classify_events([event])
        assert len(items) == 1
        assert items[0].item_type == WorkItemType.EMPTY_CONTENT

    def test_mismatched_tool_result_orphaned(self):
        """Tool result with non-matching ID is orphaned, pending tool_use preserved."""
        tu = _tool_use_event("Read", "tu-1")
        tr = _tool_result_event("tu-WRONG", "content")
        tr2 = _tool_result_event("tu-1", "real content")
        items = classify_events([tu, tr, tr2])
        assert len(items) == 2
        assert items[0].item_type == WorkItemType.ORPHANED_RESULT
        assert items[0].events == [tr]
        assert items[1].item_type == WorkItemType.TOOL_PAIR
        assert items[1].events == [tu, tr2]

    def test_empty_input(self):
        assert classify_events([]) == []

    def test_full_sequence(self):
        """prompt → thinking → tool_pair → thinking → response = 5 items."""
        events = [
            _user_text_event("help me implement JWT authentication for the entire API system"),
            _thinking_event("weighing JWT vs session tokens for this use case"),
            _tool_use_event("Read", "tu-1"),
            _tool_result_event("tu-1", "content"),
            _thinking_event("the auth module looks good, will extend it"),
            _assistant_event("I found the auth module and here is what I see in the codebase"),
        ]
        items = classify_events(events)
        assert len(items) == 5
        assert items[0].item_type == WorkItemType.PROMPT
        assert items[1].item_type == WorkItemType.THINKING
        assert items[2].item_type == WorkItemType.TOOL_PAIR
        assert items[3].item_type == WorkItemType.THINKING
        assert items[4].item_type == WorkItemType.RESPONSE

    def test_every_event_accounted_for(self):
        """Every input event appears in exactly one classified item."""
        events = [
            _user_text_event("help me implement JWT authentication for the entire API system"),
            _thinking_event("considering the best approach for JWT implementation"),
            _tool_use_event("Read", "tu-1"),
            _tool_result_event("tu-1", "content"),
            _progress_event(),
            _assistant_event("I found the authentication module and here's what I see"),
        ]
        items = classify_events(events)
        output_events = []
        for item in items:
            output_events.extend(item.events)
        assert len(output_events) == len(events)
        for event in events:
            assert event in output_events


# ---------------------------------------------------------------------------
# Integration tests — refine_batch with real DB
# ---------------------------------------------------------------------------


def _insert_raw_events(db, transcript_id: int, events: list[dict]) -> list[int]:
    """Insert raw event rows and return their IDs."""
    ids = []
    with db.session() as session:
        for evt in events:
            row = RawEventSchema(
                transcript_id=transcript_id,
                event_type=evt["event_type"],
                timestamp=evt.get("timestamp", NOW),
                content=evt["content"],
                processed=RawEventStatus.PENDING,
            )
            session.add(row)
            session.flush()
            ids.append(row.id)
    return ids


def _setup_transcript(db, tmp_path) -> int:
    """Create a project and transcript, return the transcript ID."""
    with db.session() as session:
        proj = ProjectSchema(name="test-proj", repo_path=str(tmp_path / "test"))
        session.add(proj)
        session.flush()
        tr = TranscriptSchema(project_id=proj.id, session_id="sess-1", path=str(tmp_path / "t"))
        session.add(tr)
        session.flush()
        return tr.id


class TestRefineBatch:
    def test_classifies_and_refines_prompt(self, db, tmp_path):
        """Prompt event gets classified into WorkItem, then refined into TranscriptEvent."""
        transcript_id = _setup_transcript(db, tmp_path)
        text = "help me implement JWT authentication for the entire API system"
        content = json.dumps({"type": "user", "message": {"role": "user", "content": text}})
        _insert_raw_events(db, transcript_id, [{"event_type": "user", "content": content}])

        count = EventRefiner.refine_batch(db)
        assert count == 1

        items = WorkItem.get_by_processed(WorkItemStage.REFINED, limit=100)
        assert len(items) == 1
        assert items[0].item_type == WorkItemType.PROMPT

        # TranscriptEvent created
        with db.session() as session:
            tes = session.query(TranscriptEventSchema).filter_by(transcript_id=transcript_id).all()
            assert len(tes) == 1
            assert text in tes[0].text

        # No artifact created (prompts are not artifacts)
        with db.session() as session:
            artifacts = session.query(ArtifactSchema).filter_by(transcript_id=transcript_id).all()
            assert len(artifacts) == 0

    def test_classifies_tool_pair(self, db, tmp_path):
        """Tool use + result get classified into a TOOL_PAIR WorkItem."""
        transcript_id = _setup_transcript(db, tmp_path)
        tu_content = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "tu-1", "name": "Read", "input": {}}],
                },
            }
        )
        tr_content = json.dumps(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "tu-1", "content": "ok"}],
                },
            }
        )
        event_ids = _insert_raw_events(
            db,
            transcript_id,
            [
                {"event_type": "assistant", "content": tu_content, "timestamp": _ts(0)},
                {"event_type": "user", "content": tr_content, "timestamp": _ts(1)},
            ],
        )

        with patch("observer.pipeline.refining.refinement.summarize_tool_pair") as mock_tool:
            mock_tool.return_value = ToolSummaryResult(summary="Read: auth.py → found JWT")
            count = EventRefiner.refine_batch(db)

        assert count == 1
        items = WorkItem.get_by_processed(WorkItemStage.REFINED, limit=100)
        assert len(items) == 1
        assert items[0].item_type == WorkItemType.TOOL_PAIR
        assert items[0].event_ids == event_ids

    def test_trailing_tool_use_stays_pending_when_fresh(self, db, tmp_path):
        """Recent trailing tool_use stays PENDING — result may still arrive."""
        transcript_id = _setup_transcript(db, tmp_path)
        tu_content = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "tu-1", "name": "Read", "input": {}}],
                },
            }
        )
        fresh_ts = datetime.now(UTC)
        event_ids = _insert_raw_events(
            db,
            transcript_id,
            [{"event_type": "assistant", "content": tu_content, "timestamp": fresh_ts}],
        )

        count = EventRefiner.refine_batch(db)
        assert count == 0

        with db.session() as session:
            row = session.query(RawEventSchema).filter_by(id=event_ids[0]).one()
            assert row.processed == RawEventStatus.PENDING

    def test_trailing_tool_use_skipped_when_stale(self, db, tmp_path):
        """Trailing tool_use older than stale threshold gets marked SKIPPED."""
        transcript_id = _setup_transcript(db, tmp_path)
        tu_content = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "tu-1", "name": "Read", "input": {}}],
                },
            }
        )
        stale_ts = datetime.now(UTC) - timedelta(seconds=600)
        event_ids = _insert_raw_events(
            db,
            transcript_id,
            [{"event_type": "assistant", "content": tu_content, "timestamp": stale_ts}],
        )

        count = EventRefiner.refine_batch(db)
        assert count == 0

        # Event should be SKIPPED, not stuck as PENDING
        with db.session() as session:
            row = session.query(RawEventSchema).filter_by(id=event_ids[0]).one()
            assert row.processed == RawEventStatus.SKIPPED

        # Should no longer show as pending
        assert not EventGrouper.has_pending()

    def test_has_pending(self, db, tmp_path):
        transcript_id = _setup_transcript(db, tmp_path)
        assert not EventGrouper.has_pending()
        assert not WorkItemRefiner.has_pending()

        content = json.dumps({"type": "user", "message": {"role": "user", "content": "x" * 60}})
        _insert_raw_events(db, transcript_id, [{"event_type": "user", "content": content}])
        assert EventGrouper.has_pending()

    def test_empty_batch_returns_zero(self, db, tmp_path):
        _setup_transcript(db, tmp_path)
        assert EventRefiner.refine_batch(db) == 0

    @patch("observer.pipeline.refining.refinement.summarize_tool_pair")
    @patch("observer.pipeline.refining.refinement.summarize_thinking")
    def test_full_sequence_classifies_and_refines(self, mock_thinking, mock_tool, db, tmp_path):
        """prompt → thinking → tool_pair → thinking → response = 5 refined WorkItems."""
        mock_thinking.return_value = "Thinking: analysis summary"
        mock_tool.return_value = ToolSummaryResult(summary="Read: auth.py → found JWT")

        transcript_id = _setup_transcript(db, tmp_path)

        prompt_text = "help me implement JWT authentication for the entire API system"
        thinking_1 = "weighing JWT vs session tokens for this use case and beyond"
        thinking_2 = "the auth module looks good and I will extend it for the task"
        response_text = "I found the auth module and here is what I see in the codebase"

        events_data = [
            {
                "event_type": "user",
                "content": json.dumps({"type": "user", "message": {"role": "user", "content": prompt_text}}),
                "timestamp": _ts(0),
            },
            {
                "event_type": "assistant",
                "content": json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "thinking", "thinking": thinking_1, "signature": "s"}],
                        },
                    }
                ),
                "timestamp": _ts(1),
            },
            {
                "event_type": "assistant",
                "content": json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "tool_use", "id": "tu-1", "name": "Read", "input": {}}],
                        },
                    }
                ),
                "timestamp": _ts(2),
            },
            {
                "event_type": "user",
                "content": json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": [{"type": "tool_result", "tool_use_id": "tu-1", "content": "ok"}],
                        },
                    }
                ),
                "timestamp": _ts(3),
            },
            {
                "event_type": "assistant",
                "content": json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "thinking", "thinking": thinking_2, "signature": "s"}],
                        },
                    }
                ),
                "timestamp": _ts(4),
            },
            {
                "event_type": "assistant",
                "content": json.dumps(
                    {
                        "type": "assistant",
                        "message": {"role": "assistant", "content": response_text},
                    }
                ),
                "timestamp": _ts(5),
            },
        ]
        _insert_raw_events(db, transcript_id, events_data)

        count = EventRefiner.refine_batch(db)
        assert count == 5

        refined = WorkItem.get_by_processed(WorkItemStage.REFINED, limit=100)
        assert len(refined) == 5

        types = [wi.item_type for wi in refined]
        assert types == [
            WorkItemType.PROMPT,
            WorkItemType.THINKING,
            WorkItemType.TOOL_PAIR,
            WorkItemType.THINKING,
            WorkItemType.RESPONSE,
        ]

        # TranscriptEvents created for each refined item
        with db.session() as session:
            tes = session.query(TranscriptEventSchema).filter_by(transcript_id=transcript_id).all()
            # prompt + 2 thinking + tool_pair + response = 5
            assert len(tes) == 5

    def test_skipped_item_marked_terminal(self, db, tmp_path):
        """Skipped items go straight to TERMINAL."""
        transcript_id = _setup_transcript(db, tmp_path)
        content = json.dumps({"type": "progress", "message": {"content": "hook running"}})
        _insert_raw_events(db, transcript_id, [{"event_type": "progress", "content": content}])

        EventRefiner.refine_batch(db)

        skipped = WorkItem.get_by_processed(WorkItemStage.TERMINAL, limit=100)
        assert len(skipped) == 1
        assert skipped[0].item_type == WorkItemType.UNRECOGNIZED

    @patch("observer.pipeline.refining.refinement.summarize_thinking")
    def test_thinking_llm_failure_marks_error(self, mock_thinking, db, tmp_path):
        """LLM failure during thinking refinement marks ERROR."""
        mock_thinking.side_effect = ExtractionError("LLM failed")

        transcript_id = _setup_transcript(db, tmp_path)
        content = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "thinking", "thinking": "deep analysis of the system", "signature": "s"}],
                },
            }
        )
        _insert_raw_events(db, transcript_id, [{"event_type": "assistant", "content": content}])

        EventRefiner.refine_batch(db)

        errors = WorkItem.get_by_processed(WorkItemStage.ERROR, limit=100)
        assert len(errors) == 1

    @patch("observer.pipeline.refining.refinement.summarize_tool_pair")
    def test_mutation_tool_creates_action_artifact(self, mock_tool, db, tmp_path):
        """Edit tool pair produces an ACTION artifact."""
        mock_tool.return_value = ToolSummaryResult(summary="Edit: auth.py → added redirect")

        transcript_id = _setup_transcript(db, tmp_path)

        # Add a prompt first (for prompt_event_id tracking)
        prompt_text = "implement auth redirect for the backend system now please"
        prompt_content = json.dumps({"type": "user", "message": {"role": "user", "content": prompt_text}})
        tu_content = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "tu-1", "name": "Edit", "input": {}}],
                },
            }
        )
        tr_content = json.dumps(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "tu-1", "content": "ok"}],
                },
            }
        )
        _insert_raw_events(
            db,
            transcript_id,
            [
                {"event_type": "user", "content": prompt_content, "timestamp": _ts(0)},
                {"event_type": "assistant", "content": tu_content, "timestamp": _ts(1)},
                {"event_type": "user", "content": tr_content, "timestamp": _ts(2)},
            ],
        )

        EventRefiner.refine_batch(db)

        with db.session() as session:
            actions = session.query(ArtifactSchema).filter_by(artifact_type=ArtifactType.ACTION.value).all()
            assert len(actions) == 1
            assert actions[0].prompt_event_id is not None
