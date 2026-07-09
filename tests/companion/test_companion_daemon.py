"""Tests for the daemon summary client."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from basecamp.companion.daemon import (
    DaemonAgentMessage,
    DaemonAgentMessagesError,
    DaemonAgentMessagesOk,
    DaemonAgentMessagesUnavailable,
    DaemonSkillInvocation,
    DaemonSummaryAgent,
    DaemonSummaryError,
    DaemonSummaryOk,
    DaemonSummarySource,
    DaemonSummaryUnavailable,
)


class _FakeHTTPResponse:
    def __init__(self, status: int, payload: str) -> None:
        self.status = status
        self._payload = payload.encode("utf-8")

    def read(self) -> bytes:
        return self._payload


def _build_fake_connection(payload: str, status: int = 200):
    captured: dict[str, object] = {}

    class FakeHTTPConnection:
        def __init__(self, uds_path: str, *, timeout: float) -> None:
            captured["uds_path"] = uds_path
            captured["timeout"] = timeout

        def request(self, method: str, path: str, headers: dict[str, str] | None = None, body: object = None) -> None:
            captured["method"] = method
            captured["path"] = path
            captured["headers"] = headers or {}
            captured["body"] = body

        def getresponse(self) -> _FakeHTTPResponse:
            return _FakeHTTPResponse(status, payload)

        def close(self) -> None:
            captured["closed"] = True

    return FakeHTTPConnection, captured


def test_poll_parses_summary_and_encodes_root_id_and_limit() -> None:
    payload = {
        "session_active": True,
        "root_id": "root",
        "counts": {
            "pending": 0,
            "running": 1,
            "completed": 2,
            "failed": 3,
            "total": 6,
        },
        "agents": [
            {
                "agent_handle": "mossy-otter-b2c3d4",
                "agent_id_short": "def456",
                "agent_type": "scout",
                "model": "claude-sonnet-4-5",
                "role": "agent",
                "session_name": "scout",
                "status": "completed",
                "result_preview": "ok",
                "error_preview": None,
                "exit_code": 0,
                "created_at": "2026-01-01T00:00:00Z",
                "started_at": None,
                "ended_at": None,
                "result": "full result should be dropped",
                "error": "full error should be dropped",
                "spec_json": '{"k":"v"}',
                "report_token_hash": "redacted",
            }
        ],
    }

    fake_connection, captured = _build_fake_connection(json.dumps(payload))
    source = DaemonSummarySource("/tmp/daemon.sock", connection_factory=fake_connection)
    result = source.poll("root&child", limit=7)

    assert isinstance(result, DaemonSummaryOk)
    assert result.state == "ok"
    assert result.root_id == "root"
    assert result.counts.total == 6
    assert result.session_active is True
    assert len(result.agents) == 1
    assert result.agents[0] == DaemonSummaryAgent(
        agent_handle="mossy-otter-b2c3d4",
        agent_type="scout",
        role="agent",
        session_name="scout",
        status="completed",
        result_preview="ok",
        error_preview=None,
        exit_code=0,
        created_at="2026-01-01T00:00:00Z",
        started_at=None,
        ended_at=None,
        agent_id_short="def456",
        model="claude-sonnet-4-5",
        task=None,
        recent_activity=None,
        skills=None,
    )
    assert set(asdict(result.agents[0]).keys()) == {
        "agent_handle",
        "agent_type",
        "role",
        "session_name",
        "status",
        "result_preview",
        "error_preview",
        "exit_code",
        "created_at",
        "started_at",
        "ended_at",
        "agent_id_short",
        "model",
        "task",
        "recent_activity",
        "skills",
    }

    parsed = parse_qs(urlsplit(captured["path"]).query)
    assert parsed.keys() == {"root_id", "limit"}
    assert parsed["root_id"] == ["root&child"]
    assert parsed["limit"] == ["7"]
    assert captured["method"] == "GET"
    assert captured["timeout"] == 0.5


def test_daemon_parser_reads_agent_skills() -> None:
    payload = {
        "session_active": True,
        "root_id": "root",
        "counts": {
            "pending": 0,
            "running": 1,
            "completed": 0,
            "failed": 0,
            "total": 1,
        },
        "agents": [
            {
                "agent_handle": "mossy-otter-b2c3d4",
                "agent_type": "scout",
                "role": "agent",
                "session_name": "scout",
                "status": "running",
                "result_preview": None,
                "error_preview": None,
                "exit_code": None,
                "created_at": "2026-01-01T00:00:00Z",
                "started_at": "2026-01-01T00:00:01Z",
                "ended_at": None,
                "skills": [
                    {
                        "name": "python-development",
                        "count": 2,
                        "last_seq": 12,
                        "last_timestamp": "2026-01-01T00:00:04Z",
                    },
                    {
                        "name": "sql",
                        "count": 1,
                        "last_seq": None,
                        "last_timestamp": None,
                    },
                    {"name": "x"},
                    "invalid",
                ],
            }
        ],
    }
    fake_connection, _ = _build_fake_connection(json.dumps(payload))
    source = DaemonSummarySource("/tmp/daemon.sock", connection_factory=fake_connection)

    result = source.poll("root")

    assert isinstance(result, DaemonSummaryOk)
    assert result.agents[0].skills == [
        DaemonSkillInvocation(
            name="python-development",
            count=2,
            last_seq=12,
            last_timestamp="2026-01-01T00:00:04Z",
        ),
        DaemonSkillInvocation(
            name="sql",
            count=1,
            last_seq=None,
            last_timestamp=None,
        ),
    ]


def test_poll_messages_parses_payload_and_encodes_params() -> None:
    payload = {
        "root_id": "root",
        "agent_handle": "brisk-lynx-a1b2c3",
        "messages": [
            {
                "kind": "assistant_output",
                "seq": 4,
                "timestamp": "2026-01-01T00:00:03Z",
                "label": "assistant",
                "text": "full\nmessage",
                "raw": "ignored",
                "toolCallId": "ignored",
            }
        ],
    }
    fake_connection, captured = _build_fake_connection(json.dumps(payload))
    source = DaemonSummarySource("/tmp/daemon.sock", connection_factory=fake_connection)

    result = source.poll_messages("root&child", "brisk/lynx", limit=3)

    assert isinstance(result, DaemonAgentMessagesOk)
    assert result.root_id == "root"
    assert result.agent_handle == "brisk-lynx-a1b2c3"
    assert result.messages == [
        DaemonAgentMessage(
            kind="assistant_output",
            seq=4,
            timestamp="2026-01-01T00:00:03Z",
            label="assistant",
            text="full\nmessage",
        )
    ]
    assert set(asdict(result.messages[0]).keys()) == {"kind", "seq", "timestamp", "label", "text"}

    parsed = parse_qs(urlsplit(captured["path"]).query)
    assert captured["method"] == "GET"
    assert urlsplit(captured["path"]).path == "/runs/messages"
    assert parsed == {
        "root_id": ["root&child"],
        "agent_handle": ["brisk/lynx"],
        "limit": ["3"],
    }


def test_poll_messages_returns_error_for_invalid_response_shape() -> None:
    fake_connection, _ = _build_fake_connection(json.dumps({"root_id": "root", "messages": ["bad"]}))
    source = DaemonSummarySource("/tmp/daemon.sock", connection_factory=fake_connection)

    result = source.poll_messages("root", "agent")

    assert isinstance(result, DaemonAgentMessagesError)
    assert result.state == "error"


def test_poll_messages_returns_unavailable_when_socket_missing(tmp_path: Path) -> None:
    missing_path = tmp_path / "daemon.sock"
    source = DaemonSummarySource(missing_path)

    result = source.poll_messages("root", "agent")

    assert isinstance(result, DaemonAgentMessagesUnavailable)
    assert result.state == "unavailable"


def test_poll_returns_unavailable_when_socket_missing(tmp_path: Path) -> None:
    missing_path = tmp_path / "daemon.sock"
    source = DaemonSummarySource(missing_path)

    result = source.poll("root")

    assert isinstance(result, DaemonSummaryUnavailable)
    assert result.state == "unavailable"


def test_poll_returns_error_for_malformed_json() -> None:
    fake_connection, _ = _build_fake_connection("{this-is-not-json")
    source = DaemonSummarySource("/tmp/daemon.sock", connection_factory=fake_connection)

    result = source.poll("root")

    assert isinstance(result, DaemonSummaryError)
    assert result.state == "error"


def test_poll_returns_error_for_invalid_response_shape() -> None:
    payload = {
        "session_active": True,
        "root_id": "root",
        "counts": {
            "pending": 0,
            "running": 1,
            "completed": 2,
            "failed": 3,
            "total": 6,
        },
        "agents": ["invalid"],
    }
    fake_connection, _ = _build_fake_connection(json.dumps(payload))
    source = DaemonSummarySource("/tmp/daemon.sock", connection_factory=fake_connection)

    result = source.poll("root")

    assert isinstance(result, DaemonSummaryError)
    assert result.state == "error"


def test_poll_parses_inactive_session() -> None:
    payload = {
        "session_active": False,
        "root_id": "root",
        "counts": {
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "total": 0,
        },
        "agents": [],
    }
    fake_connection, _ = _build_fake_connection(json.dumps(payload))
    source = DaemonSummarySource("/tmp/daemon.sock", connection_factory=fake_connection)

    result = source.poll("root")

    assert isinstance(result, DaemonSummaryOk)
    assert result.session_active is False


def test_poll_returns_error_for_http_error_status() -> None:
    fake_connection, _ = _build_fake_connection("{}", status=500)
    source = DaemonSummarySource("/tmp/daemon.sock", connection_factory=fake_connection)

    result = source.poll("root")

    assert isinstance(result, DaemonSummaryError)
    assert result.state == "error"
