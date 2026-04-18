"""Tests for observer.parser."""

import json
from datetime import UTC, datetime

from observer.pipeline.parser import ParsedEvent, TranscriptParser

from tests.pi_fixtures import (
    make_assistant_message,
    make_model_change,
    make_session_header,
    make_tool_result,
    make_user_message,
)


def _write_jsonl(path, lines: list[dict]) -> None:
    """Write a list of dicts as JSONL to *path*."""
    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def _make_event(
    event_type: str = "user",
    timestamp: str = "2025-01-15T10:00:00Z",
    uuid: str | None = "abc-123",
    **extra,
) -> dict:
    """Build a minimal JSONL event dict."""
    d: dict = {"type": event_type, "timestamp": timestamp, **extra}
    if uuid is not None:
        d["uuid"] = uuid
    return d


class TestParseTranscript:
    def test_parse_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        events, offset = TranscriptParser().parse(path)
        assert events == []
        assert offset == 0

    def test_parse_user_event(self, tmp_path):
        path = tmp_path / "t.jsonl"
        ev = _make_event("user", uuid="u-1")
        _write_jsonl(path, [ev])

        events, _ = TranscriptParser().parse(path)
        assert len(events) == 1
        assert events[0].event_type == "user"
        assert events[0].message_uuid == "u-1"
        assert events[0].timestamp == datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        assert json.loads(events[0].content) == ev

    def test_parse_assistant_event(self, tmp_path):
        path = tmp_path / "t.jsonl"
        _write_jsonl(path, [_make_event("assistant", uuid="a-1")])

        events, _ = TranscriptParser().parse(path)
        assert len(events) == 1
        assert events[0].event_type == "assistant"

    def test_parse_system_event(self, tmp_path):
        path = tmp_path / "t.jsonl"
        _write_jsonl(path, [_make_event("system", uuid="s-1", subtype="turn_duration")])

        events, _ = TranscriptParser().parse(path)
        assert len(events) == 1
        assert events[0].event_type == "system"

    def test_parse_progress_event(self, tmp_path):
        path = tmp_path / "t.jsonl"
        _write_jsonl(path, [_make_event("progress", uuid="p-1")])

        events, _ = TranscriptParser().parse(path)
        assert len(events) == 1
        assert events[0].event_type == "progress"

    def test_parse_multiple_events(self, tmp_path):
        path = tmp_path / "t.jsonl"
        lines = [
            _make_event("user", timestamp="2025-01-15T10:00:00Z", uuid="u-1"),
            _make_event("assistant", timestamp="2025-01-15T10:00:01Z", uuid="a-1"),
            _make_event("system", timestamp="2025-01-15T10:00:02Z", uuid="s-1"),
        ]
        _write_jsonl(path, lines)

        events, _ = TranscriptParser().parse(path)
        assert len(events) == 3
        assert [e.event_type for e in events] == ["user", "assistant", "system"]

    def test_parse_from_offset(self, tmp_path):
        path = tmp_path / "t.jsonl"
        lines = [
            _make_event("user", uuid="u-1"),
            _make_event("assistant", uuid="a-1"),
        ]
        _write_jsonl(path, lines)

        # First parse: get all events and the offset
        all_events, offset = TranscriptParser().parse(path)
        assert len(all_events) == 2

        # Second parse from offset: nothing new
        events, new_offset = TranscriptParser().parse(path, offset)
        assert events == []
        assert new_offset == offset

    def test_offset_advances(self, tmp_path):
        path = tmp_path / "t.jsonl"
        _write_jsonl(path, [_make_event("user")])
        file_size = path.stat().st_size

        _, offset = TranscriptParser().parse(path)
        assert offset == file_size

    def test_skips_file_history_snapshot(self, tmp_path):
        path = tmp_path / "t.jsonl"
        lines = [
            _make_event("user", uuid="u-1"),
            {"type": "file-history-snapshot", "snapshot": {"timestamp": "2025-01-15T10:00:00Z"}},
            _make_event("assistant", uuid="a-1"),
        ]
        _write_jsonl(path, lines)

        events, _ = TranscriptParser().parse(path)
        assert len(events) == 2
        assert all(e.event_type != "file-history-snapshot" for e in events)

    def test_skips_malformed_json(self, tmp_path):
        path = tmp_path / "t.jsonl"
        with open(path, "w") as f:
            f.write(json.dumps(_make_event("user", uuid="u-1")) + "\n")
            f.write("NOT VALID JSON{{{}\n")
            f.write(json.dumps(_make_event("assistant", uuid="a-1")) + "\n")

        events, _ = TranscriptParser().parse(path)
        assert len(events) == 2

    def test_skips_missing_timestamp(self, tmp_path):
        path = tmp_path / "t.jsonl"
        lines = [
            _make_event("user", uuid="u-1"),
            {"type": "system", "uuid": "no-ts"},  # no timestamp
            _make_event("assistant", uuid="a-1"),
        ]
        _write_jsonl(path, lines)

        events, _ = TranscriptParser().parse(path)
        assert len(events) == 2

    def test_missing_uuid(self, tmp_path):
        path = tmp_path / "t.jsonl"
        _write_jsonl(path, [_make_event("system", uuid=None, subtype="turn_duration")])

        events, _ = TranscriptParser().parse(path)
        assert len(events) == 1
        assert events[0].message_uuid is None

    def test_partial_line_at_eof(self, tmp_path):
        path = tmp_path / "t.jsonl"
        complete = _make_event("user", uuid="u-1")

        # Write one complete line + one partial line (no trailing newline)
        with open(path, "w") as f:
            f.write(json.dumps(complete) + "\n")
            f.write('{"type": "assistant", "timest')  # truncated

        events, offset = TranscriptParser().parse(path)
        assert len(events) == 1
        assert events[0].event_type == "user"
        # Offset should stop at end of the complete line, not the partial one
        complete_line = json.dumps(complete) + "\n"
        assert offset == len(complete_line.encode("utf-8"))

    def test_queue_operation_event(self, tmp_path):
        path = tmp_path / "t.jsonl"
        _write_jsonl(path, [_make_event("queue-operation", uuid="q-1", operation="enqueue")])

        events, _ = TranscriptParser().parse(path)
        assert len(events) == 1
        assert events[0].event_type == "queue-operation"

    def test_frozen_dataclass(self):
        ev = ParsedEvent(
            event_type="user",
            timestamp=datetime.now(UTC),
            content="{}",
            message_uuid="x",
        )
        # ParsedEvent is frozen — mutation should raise
        try:
            ev.event_type = "other"  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")  # noqa: TRY003
        except AttributeError:
            pass

    def test_incremental_reads(self, tmp_path):
        """Simulate a growing file: parse, append, parse again."""
        path = tmp_path / "t.jsonl"
        _write_jsonl(path, [_make_event("user", uuid="u-1")])

        events1, offset1 = TranscriptParser().parse(path)
        assert len(events1) == 1

        # Append another event
        with open(path, "a") as f:
            f.write(json.dumps(_make_event("assistant", uuid="a-1")) + "\n")

        events2, offset2 = TranscriptParser().parse(path, offset1)
        assert len(events2) == 1
        assert events2[0].event_type == "assistant"
        assert offset2 > offset1
        assert offset2 == path.stat().st_size

    def test_claude_source_field(self, tmp_path):
        """Claude format events have source='claude'."""
        path = tmp_path / "t.jsonl"
        _write_jsonl(path, [_make_event("user", uuid="u-1")])
        events, _ = TranscriptParser().parse(path)
        assert events[0].source == "claude"


class TestPiFormatParsing:
    """Tests for pi JSONL format auto-detection and parsing."""

    def _write_lines(self, path, lines: list[str]) -> None:
        with open(path, "w") as f:
            for line in lines:
                f.write(line + "\n")

    def test_parse_user_message(self, tmp_path):
        path = tmp_path / "t.jsonl"
        self._write_lines(path, [make_user_message("hello", entry_id="a1b2c3d4")])
        events, _ = TranscriptParser().parse(path)
        assert len(events) == 1
        assert events[0].event_type == "user"
        assert events[0].message_uuid == "a1b2c3d4"
        assert events[0].source == "pi"
        assert events[0].timestamp == datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)

    def test_parse_assistant_message(self, tmp_path):
        path = tmp_path / "t.jsonl"
        self._write_lines(path, [make_assistant_message(text="hi")])
        events, _ = TranscriptParser().parse(path)
        assert len(events) == 1
        assert events[0].event_type == "assistant"
        assert events[0].source == "pi"

    def test_parse_tool_result_message(self, tmp_path):
        path = tmp_path / "t.jsonl"
        self._write_lines(path, [make_tool_result("tc-1", "read", "file contents")])
        events, _ = TranscriptParser().parse(path)
        assert len(events) == 1
        assert events[0].event_type == "toolResult"
        assert events[0].source == "pi"

    def test_skips_session_header(self, tmp_path):
        path = tmp_path / "t.jsonl"
        self._write_lines(
            path,
            [
                make_session_header(),
                make_user_message("hello"),
            ],
        )
        events, _ = TranscriptParser().parse(path)
        assert len(events) == 1
        assert events[0].event_type == "user"

    def test_skips_model_change(self, tmp_path):
        path = tmp_path / "t.jsonl"
        self._write_lines(
            path,
            [
                make_model_change(),
                make_user_message("hello"),
            ],
        )
        events, _ = TranscriptParser().parse(path)
        assert len(events) == 1
        assert events[0].event_type == "user"

    def test_skips_all_non_message_types(self, tmp_path):
        path = tmp_path / "t.jsonl"
        skip_types = [
            '{"type": "session", "version": 3, "id": "x", "timestamp": "2026-01-01T00:00:00Z", "cwd": "/tmp"}',
            '{"type": "model_change", "model": "m", "timestamp": "2026-01-01T00:00:00Z"}',
            '{"type": "thinking_level_change", "level": "high", "timestamp": "2026-01-01T00:00:00Z"}',
            '{"type": "session_info", "info": {}, "timestamp": "2026-01-01T00:00:00Z"}',
            '{"type": "label", "text": "test", "timestamp": "2026-01-01T00:00:00Z"}',
            '{"type": "custom", "data": {}, "timestamp": "2026-01-01T00:00:00Z"}',
            '{"type": "custom_message", "data": {}, "timestamp": "2026-01-01T00:00:00Z"}',
            '{"type": "compaction", "timestamp": "2026-01-01T00:00:00Z"}',
            '{"type": "branch_summary", "summary": "x", "timestamp": "2026-01-01T00:00:00Z"}',
        ]
        lines = skip_types + [make_user_message("hello")]
        self._write_lines(path, lines)
        events, _ = TranscriptParser().parse(path)
        assert len(events) == 1
        assert events[0].event_type == "user"

    def test_full_pi_session(self, tmp_path):
        """Parse a complete pi session with mixed entry types."""
        path = tmp_path / "t.jsonl"
        self._write_lines(
            path,
            [
                make_session_header(),
                make_user_message("help me", entry_id="a1", timestamp="2026-01-01T00:00:01Z"),
                make_assistant_message(
                    tool_calls=[{"id": "tc-1", "name": "read", "arguments": {"path": "/a.py"}}],
                    entry_id="b1",
                    parent_id="a1",
                    timestamp="2026-01-01T00:00:02Z",
                ),
                make_tool_result(
                    "tc-1",
                    "read",
                    "file contents",
                    entry_id="c1",
                    parent_id="b1",
                    timestamp="2026-01-01T00:00:03Z",
                ),
                make_assistant_message(
                    text="Here's what I found",
                    entry_id="d1",
                    parent_id="c1",
                    timestamp="2026-01-01T00:00:04Z",
                ),
            ],
        )
        events, _ = TranscriptParser().parse(path)
        assert len(events) == 4
        assert [e.event_type for e in events] == ["user", "assistant", "toolResult", "assistant"]
        assert all(e.source == "pi" for e in events)

    def test_mixed_format_file(self, tmp_path):
        """Auto-detection works per-line even in a mixed file."""
        path = tmp_path / "t.jsonl"
        claude_line = json.dumps(_make_event("user", uuid="u-1"))
        pi_line = make_user_message("hello from pi", entry_id="p1")
        with open(path, "w") as f:
            f.write(claude_line + "\n")
            f.write(pi_line + "\n")
        events, _ = TranscriptParser().parse(path)
        assert len(events) == 2
        assert events[0].source == "claude"
        assert events[1].source == "pi"

    def test_message_without_role_skipped(self, tmp_path):
        path = tmp_path / "t.jsonl"
        bad_line = json.dumps(
            {
                "type": "message",
                "id": "x1",
                "timestamp": "2026-01-01T00:00:01Z",
                "message": {"content": [{"type": "text", "text": "no role"}]},
            }
        )
        self._write_lines(path, [bad_line])
        events, _ = TranscriptParser().parse(path)
        assert len(events) == 0

    def test_message_without_timestamp_skipped(self, tmp_path):
        path = tmp_path / "t.jsonl"
        bad_line = json.dumps(
            {
                "type": "message",
                "id": "x1",
                "message": {"role": "user", "content": [{"type": "text", "text": "no ts"}]},
            }
        )
        self._write_lines(path, [bad_line])
        events, _ = TranscriptParser().parse(path)
        assert len(events) == 0

    def test_incremental_reads_pi(self, tmp_path):
        path = tmp_path / "t.jsonl"
        self._write_lines(path, [make_user_message("first", entry_id="a1")])
        events1, offset1 = TranscriptParser().parse(path)
        assert len(events1) == 1

        with open(path, "a") as f:
            f.write(make_assistant_message(text="second", entry_id="b1") + "\n")

        events2, offset2 = TranscriptParser().parse(path, offset1)
        assert len(events2) == 1
        assert events2[0].event_type == "assistant"
        assert offset2 > offset1
