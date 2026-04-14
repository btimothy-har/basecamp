"""Pi-format JSONL fixture helpers for tests."""

import json
from datetime import datetime


def make_session_header(session_id="test-session", cwd="/tmp/test"):
    return json.dumps(
        {
            "type": "session",
            "version": 3,
            "id": session_id,
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": cwd,
        }
    )


def make_model_change(model="claude-sonnet-4-5", timestamp="2026-01-01T00:00:00.500Z"):
    return json.dumps(
        {
            "type": "model_change",
            "model": model,
            "timestamp": timestamp,
        }
    )


def make_user_message(
    text,
    entry_id="a1b2c3d4",
    parent_id=None,
    timestamp="2026-01-01T00:00:01Z",
):
    return json.dumps(
        {
            "type": "message",
            "id": entry_id,
            "parentId": parent_id,
            "timestamp": timestamp,
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": text}],
                "timestamp": int(datetime.fromisoformat(timestamp).timestamp() * 1000),
            },
        }
    )


def make_assistant_message(
    text=None,
    tool_calls=None,
    thinking=None,
    entry_id="b2c3d4e5",
    parent_id="a1b2c3d4",
    timestamp="2026-01-01T00:00:02Z",
):
    content = []
    if thinking:
        content.append({"type": "thinking", "thinking": thinking})
    if text:
        content.append({"type": "text", "text": text})
    if tool_calls:
        content.extend(
            {
                "type": "toolCall",
                "id": tc["id"],
                "name": tc["name"],
                "arguments": tc.get("arguments", {}),
            }
            for tc in tool_calls
        )
    return json.dumps(
        {
            "type": "message",
            "id": entry_id,
            "parentId": parent_id,
            "timestamp": timestamp,
            "message": {
                "role": "assistant",
                "content": content,
                "api": "anthropic-messages",
                "provider": "anthropic",
                "model": "claude-sonnet-4-5",
                "usage": {
                    "input": 0,
                    "output": 0,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "totalTokens": 0,
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0},
                },
                "stopReason": "toolUse" if tool_calls else "stop",
                "timestamp": int(datetime.fromisoformat(timestamp).timestamp() * 1000),
            },
        }
    )


def make_tool_result(
    tool_call_id,
    tool_name,
    content_text,
    *,
    is_error=False,
    entry_id="c3d4e5f6",
    parent_id="b2c3d4e5",
    timestamp="2026-01-01T00:00:03Z",
):
    return json.dumps(
        {
            "type": "message",
            "id": entry_id,
            "parentId": parent_id,
            "timestamp": timestamp,
            "message": {
                "role": "toolResult",
                "toolCallId": tool_call_id,
                "toolName": tool_name,
                "content": [{"type": "text", "text": content_text}],
                "isError": is_error,
                "timestamp": int(datetime.fromisoformat(timestamp).timestamp() * 1000),
            },
        }
    )
