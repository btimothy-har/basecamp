"""Tests for the analysis-time reducer over raw pi thread entries."""

from __future__ import annotations

import json

from basecamp.hub.broker.analysis.reducer import reduce_thread


def _entry(entry_id: str, parent_id: str | None, **extra: object) -> str:
    return json.dumps({"id": entry_id, "parentId": parent_id, "timestamp": "t", **extra})


def _user(entry_id: str, parent_id: str | None, text: str) -> str:
    return _entry(entry_id, parent_id, type="message", message={"role": "user", "content": text})


def _assistant(entry_id: str, parent_id: str | None, content: list[dict[str, object]]) -> str:
    return _entry(entry_id, parent_id, type="message", message={"role": "assistant", "content": content})


def _tool_result(entry_id: str, parent_id: str | None, *, name: str, is_error: bool, text: str) -> str:
    message = {"role": "toolResult", "toolName": name, "isError": is_error, "content": [{"type": "text", "text": text}]}
    return _entry(entry_id, parent_id, type="message", message=message)


def test_renders_user_assistant_tool_call_and_result() -> None:
    live = [
        _user("e1", None, "hello there"),
        _assistant(
            "e2",
            "e1",
            [
                {"type": "thinking", "thinking": "let me look"},
                {"type": "text", "text": "running it"},
                {"type": "toolCall", "id": "tc1", "name": "bash", "arguments": {"cmd": "ls"}},
            ],
        ),
        _tool_result("e3", "e2", name="bash", is_error=False, text="file1\n  file2"),
    ]

    result = reduce_thread(live)

    assert "User: hello there" in result
    assert "Assistant:" in result
    assert "(thinking) let me look" in result
    assert "running it" in result
    assert "[tool: bash]" in result
    assert "[result: bash ok] file1 file2" in result  # whitespace collapsed, payload previewed


def test_tool_result_error_status_and_preview_budget() -> None:
    live = [_tool_result("e1", None, name="grep", is_error=True, text="x" * 400)]

    result = reduce_thread(live, tool_preview_budget=10)

    assert result.startswith("[result: grep error]")
    assert "…" in result
    assert "x" * 400 not in result


def test_include_thinking_false_drops_reasoning() -> None:
    live = [_assistant("e1", None, [{"type": "thinking", "thinking": "secret"}, {"type": "text", "text": "answer"}])]

    with_thinking = reduce_thread(live, include_thinking=True)
    without = reduce_thread(live, include_thinking=False)

    assert "secret" in with_thinking
    assert "secret" not in without
    assert "answer" in without


def test_applies_latest_compaction_marker() -> None:
    live = [
        _user("e0", None, "ancient prompt"),
        _user("e1", "e0", "kept question"),
        _entry("c1", "e1", type="compaction", summary="prior work summarized", firstKeptEntryId="e1", tokensBefore=99),
        _assistant("e2", "c1", [{"type": "text", "text": "the answer"}]),
    ]

    result = reduce_thread(live)

    assert "prior work summarized" in result  # summary substituted
    assert "ancient prompt" not in result  # dropped (before firstKeptEntryId)
    assert "kept question" in result  # firstKeptEntryId is kept
    assert "the answer" in result


def test_compaction_without_a_summary_keeps_context() -> None:
    live = [
        _user("e0", None, "ancient prompt"),
        _user("e1", "e0", "kept question"),
        _entry("c1", "e1", type="compaction", summary="", firstKeptEntryId="e1", tokensBefore=99),
        _assistant("e2", "c1", [{"type": "text", "text": "the answer"}]),
    ]

    result = reduce_thread(live)

    # An empty summary has nothing to substitute, so the prefix must be kept, not dropped.
    assert "ancient prompt" in result
    assert "kept question" in result
    assert "the answer" in result
    assert "compacted" not in result  # no summary line emitted


def test_no_compaction_keeps_everything() -> None:
    live = [_user("e1", None, "q"), _assistant("e2", "e1", [{"type": "text", "text": "a"}])]

    result = reduce_thread(live)

    assert "compacted" not in result
    assert "User: q" in result
    assert "Assistant:" in result and "a" in result


def test_skips_malformed_and_non_message_entries() -> None:
    live = [
        "not json at all",
        _entry("m1", None, type="model_change", provider="x", modelId="y"),
        _user("e1", "m1", "real question"),
    ]

    result = reduce_thread(live)

    assert result == "User: real question"
