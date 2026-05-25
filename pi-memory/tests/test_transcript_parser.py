from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pi_memory.constants import DEFAULT_TRANSCRIPT_ROOTS
from pi_memory.transcripts import PiTranscriptParser, discover_transcript_paths


def write_transcript(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def test_default_transcript_roots_include_pi_agent_sessions() -> None:
    assert Path.home() / ".pi" / "agent" / "sessions" in DEFAULT_TRANSCRIPT_ROOTS


def test_discover_transcript_paths_returns_sorted_jsonl_files(tmp_path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    nested_root = first_root / "nested"
    nested_root.mkdir(parents=True)
    second_root.mkdir()
    first = nested_root / "b.jsonl"
    second = second_root / "a.jsonl"
    ignored = first_root / "ignored.txt"
    write_transcript(first, b"{}\n")
    write_transcript(second, b"{}\n")
    write_transcript(ignored, b"{}\n")

    assert discover_transcript_paths([first_root, second_root, tmp_path / "missing"]) == [first, second]


def test_discover_transcript_paths_accepts_jsonl_file_root(tmp_path) -> None:
    transcript_path = tmp_path / "transcript.jsonl"
    write_transcript(transcript_path, b"{}\n")

    assert discover_transcript_paths([transcript_path]) == [transcript_path]


def test_session_id_returns_first_session_entry_id(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    write_transcript(
        path,
        b'{"type":"message","id":"message-1","message":{"role":"user"}}\n'
        b'{"type":"session","id":"session-1"}\n'
        b'{"type":"session","id":"session-2"}\n',
    )

    assert PiTranscriptParser().session_id(path) == "session-1"


def test_session_id_returns_none_when_first_session_entry_has_no_id(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    write_transcript(
        path,
        b'{"type":"session","id":"  "}\n{"type":"session","id":"session-2"}\n{"type":"message","id":"message-1"}\n',
    )

    assert PiTranscriptParser().session_id(path) is None


def test_session_id_skips_malformed_lines(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    write_transcript(path, b'{"type":"message",\n{"type":"session","id":"session-1"}\n')

    assert PiTranscriptParser().session_id(path) == "session-1"


def test_parse_empty_file(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    write_transcript(path, b"")

    result = PiTranscriptParser().parse(path)

    assert result.entries == []
    assert result.cursor_offset == 0
    assert result.file_size == 0
    assert result.malformed_lines == 0
    assert result.unsupported_lines == 0


def test_parse_from_end_offset_returns_no_new_entries(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    content = b'{"type":"session","id":"session-1"}\n'
    write_transcript(path, content)

    result = PiTranscriptParser().parse(path, offset=len(content))

    assert result.entries == []
    assert result.cursor_offset == len(content)
    assert result.file_size == len(content)


def test_parse_negative_offset_starts_at_beginning(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    content = b'{"type":"session","id":"session-1"}\n'
    write_transcript(path, content)

    result = PiTranscriptParser().parse(path, offset=-5)

    assert [entry.entry_id for entry in result.entries] == ["session-1"]
    assert result.cursor_offset == len(content)


def test_parse_clamps_cursor_when_offset_is_past_eof(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    content = b'{"type":"session","id":"session-1"}\n'
    write_transcript(path, content)

    result = PiTranscriptParser().parse(path, offset=len(content) + 100)

    assert result.entries == []
    assert result.cursor_offset == len(content)
    assert result.file_size == len(content)


def test_parse_supports_incremental_append_after_partial_trailing_line(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    complete_line = b'{"type":"session","id":"session-1"}\n'
    partial_line = b'{"type":"message","id":"message-1","message":{"role":"user"}'
    write_transcript(path, complete_line + partial_line)

    first_result = PiTranscriptParser().parse(path)

    assert [entry.entry_id for entry in first_result.entries] == ["session-1"]
    assert first_result.cursor_offset == len(complete_line)
    assert first_result.file_size == len(complete_line) + len(partial_line)

    completed_line_tail = b"}\n"
    write_transcript(path, complete_line + partial_line + completed_line_tail)

    second_result = PiTranscriptParser().parse(path, offset=first_result.cursor_offset)

    assert [entry.entry_id for entry in second_result.entries] == ["message-1"]
    assert second_result.entries[0].raw_line == (partial_line + completed_line_tail).decode()
    assert second_result.entries[0].byte_start == len(complete_line)
    assert second_result.entries[0].byte_end == len(complete_line) + len(partial_line) + len(completed_line_tail)
    assert second_result.cursor_offset == second_result.file_size


def test_parse_skips_non_object_json_lines_and_advances_cursor(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    non_object_line = b"[]\n"
    valid_line = b'{"type":"session","id":"session-1"}\n'
    write_transcript(path, non_object_line + valid_line)

    result = PiTranscriptParser().parse(path)

    assert [entry.entry_id for entry in result.entries] == ["session-1"]
    assert result.malformed_lines == 1
    assert result.cursor_offset == len(non_object_line) + len(valid_line)


def test_parse_skips_malformed_complete_lines_and_advances_cursor(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    malformed_line = b'{"type":"message",\n'
    invalid_utf8_line = b'{"type":"message","id":"bad-utf8"}\xff\n'
    valid_line = b'{"type":"model_change","id":"model-change-1"}\n'
    write_transcript(path, malformed_line + invalid_utf8_line + valid_line)

    result = PiTranscriptParser().parse(path)

    assert [entry.entry_id for entry in result.entries] == ["model-change-1"]
    assert result.malformed_lines == 2
    assert result.unsupported_lines == 0
    assert result.cursor_offset == result.file_size
    assert result.entries[0].byte_start == len(malformed_line) + len(invalid_utf8_line)


def test_parse_skips_entries_with_missing_or_non_string_type(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    missing_type_line = b'{"id":"missing-type"}\n'
    non_string_type_line = b'{"type":123,"id":"non-string-type"}\n'
    valid_line = b'{"type":"message","id":"pi-1","message":{"role":"assistant"}}\n'
    write_transcript(path, missing_type_line + non_string_type_line + valid_line)

    result = PiTranscriptParser().parse(path)

    assert [entry.entry_id for entry in result.entries] == ["pi-1"]
    assert result.unsupported_lines == 2
    assert result.malformed_lines == 0
    assert result.cursor_offset == len(missing_type_line) + len(non_string_type_line) + len(valid_line)


def test_parse_accepts_real_pi_extra_entry_types(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    custom_message_line = (
        b'{"type":"custom_message","id":"custom-message-1","parentId":"session-1","message":{"role":"user"}}\n'
    )
    session_info_line = b'{"type":"session_info","id":"session-info-1"}\n'
    thinking_level_change_line = b'{"type":"thinking_level_change","id":"thinking-level-1"}\n'
    custom_line = b'{"type":"custom","id":"custom-1"}\n'
    compaction_line = b'{"type":"compaction","id":"compaction-1"}\n'
    write_transcript(
        path,
        custom_message_line + session_info_line + thinking_level_change_line + custom_line + compaction_line,
    )

    result = PiTranscriptParser().parse(path)

    assert [entry.entry_type for entry in result.entries] == [
        "custom_message",
        "session_info",
        "thinking_level_change",
        "custom",
        "compaction",
    ]
    assert [entry.entry_id for entry in result.entries] == [
        "custom-message-1",
        "session-info-1",
        "thinking-level-1",
        "custom-1",
        "compaction-1",
    ]
    assert result.entries[0].parent_id == "session-1"
    assert [entry.message_role for entry in result.entries] == ["user", None, None, None, None]
    assert result.unsupported_lines == 0
    assert result.malformed_lines == 0


def test_parse_session_header_exposes_parent_session_path(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    session_line = b'{"type":"session","id":"session-1","parentSession":"/tmp/parent.jsonl"}\n'
    message_line = b'{"type":"message","id":"message-1","parentSession":"/tmp/ignored.jsonl"}\n'
    invalid_session_line = b'{"type":"session","id":"session-2","parentSession":{"path":"/tmp/ignored.jsonl"}}\n'
    write_transcript(path, session_line + message_line + invalid_session_line)

    result = PiTranscriptParser().parse(path)

    assert [entry.parent_session_path for entry in result.entries] == [
        "/tmp/parent.jsonl",
        None,
        None,
    ]


def test_parse_pi_session_header_and_model_change(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    session_line = b'{"type":"session","id":"session-1","timestamp":"2026-05-14T12:30:00Z"}\n'
    model_change_line = (
        b'{"type":"model_change","id":"model-change-1","parentId":"session-1",'
        b'"timestamp":"2026-05-14T12:31:00+00:00"}\n'
    )
    write_transcript(path, session_line + model_change_line)

    result = PiTranscriptParser().parse(path)

    session_entry, model_change_entry = result.entries
    assert session_entry.entry_type == "session"
    assert session_entry.entry_id == "session-1"
    assert session_entry.parent_id is None
    assert session_entry.message_role is None
    assert session_entry.timestamp == datetime(2026, 5, 14, 12, 30, tzinfo=UTC)
    assert session_entry.raw_line == session_line.decode()
    assert session_entry.byte_start == 0
    assert session_entry.byte_end == len(session_line)

    assert model_change_entry.entry_type == "model_change"
    assert model_change_entry.entry_id == "model-change-1"
    assert model_change_entry.parent_id == "session-1"
    assert model_change_entry.message_role is None
    assert model_change_entry.timestamp == datetime(2026, 5, 14, 12, 31, tzinfo=UTC)
    assert model_change_entry.raw_line == model_change_line.decode()
    assert model_change_entry.byte_start == len(session_line)
    assert model_change_entry.byte_end == len(session_line) + len(model_change_line)


def test_parse_message_roles_for_user_assistant_and_tool_result(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    user_line = b'{"type":"message","id":"user-1","message":{"role":"user"}}\n'
    assistant_line = b'{"type":"message","id":"assistant-1","parentId":"user-1","message":{"role":"assistant"}}\n'
    tool_result_line = b'{"type":"message","id":"tool-1","parentId":"assistant-1","message":{"role":"toolResult"}}\n'
    write_transcript(path, user_line + assistant_line + tool_result_line)

    result = PiTranscriptParser().parse(path)

    assert [(entry.entry_id, entry.parent_id, entry.message_role) for entry in result.entries] == [
        ("user-1", None, "user"),
        ("assistant-1", "user-1", "assistant"),
        ("tool-1", "assistant-1", "toolResult"),
    ]
    assert all(entry.entry_type == "message" for entry in result.entries)


def test_parse_handles_missing_invalid_and_naive_timestamps(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    missing_timestamp_line = b'{"type":"message","id":"missing","message":{"role":"user"}}\n'
    invalid_timestamp_line = (
        b'{"type":"message","id":"invalid","timestamp":"not-a-date","message":{"role":"assistant"}}\n'
    )
    naive_timestamp_line = (
        b'{"type":"message","id":"naive","timestamp":"2026-05-14T12:32:00","message":{"role":"assistant"}}\n'
    )
    write_transcript(path, missing_timestamp_line + invalid_timestamp_line + naive_timestamp_line)

    result = PiTranscriptParser().parse(path)

    assert [entry.timestamp for entry in result.entries] == [
        None,
        None,
        datetime(2026, 5, 14, 12, 32, tzinfo=UTC),
    ]


def test_parse_ignores_non_string_metadata_fields(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    line = b'{"type":"message","id":123,"parentId":456,"message":{"role":789}}\n'
    write_transcript(path, line)

    result = PiTranscriptParser().parse(path)

    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.entry_id is None
    assert entry.parent_id is None
    assert entry.message_role is None


def test_parse_preserves_raw_line_exactly_and_tracks_byte_spans(tmp_path) -> None:
    path = tmp_path / "transcript.jsonl"
    first_line = '{ "type" : "session", "id" : "session-é" }\r\n'.encode()
    second_line = '{"type":"message","id":"message-1","parentId":"session-é","message":{"role":"user"}}\n'.encode()
    write_transcript(path, first_line + second_line)

    result = PiTranscriptParser().parse(path)

    assert [entry.raw_line for entry in result.entries] == [first_line.decode(), second_line.decode()]
    assert [(entry.byte_start, entry.byte_end) for entry in result.entries] == [
        (0, len(first_line)),
        (len(first_line), len(first_line) + len(second_line)),
    ]
    assert result.entries[0].entry_id == "session-é"
    assert result.entries[1].parent_id == "session-é"
    assert result.cursor_offset == len(first_line) + len(second_line)
