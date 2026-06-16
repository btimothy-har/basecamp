"""Tests for the daemon summary client."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from basecamp.companion.daemon import (
    DaemonSummaryError,
    DaemonSummaryOk,
    DaemonSummaryRun,
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
        "runs": [
            {
                "run_id": "run-1",
                "agent_id": "agent-1",
                "parent_id": None,
                "role": "session",
                "session_name": "root",
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
    assert len(result.runs) == 1
    assert result.runs[0] == DaemonSummaryRun(
        run_id="run-1",
        agent_id="agent-1",
        parent_id=None,
        role="session",
        session_name="root",
        status="completed",
        result_preview="ok",
        error_preview=None,
        exit_code=0,
        created_at="2026-01-01T00:00:00Z",
        started_at=None,
        ended_at=None,
    )
    assert set(asdict(result.runs[0]).keys()) == {
        "run_id",
        "agent_id",
        "parent_id",
        "role",
        "session_name",
        "status",
        "result_preview",
        "error_preview",
        "exit_code",
        "created_at",
        "started_at",
        "ended_at",
    }

    parsed = parse_qs(urlsplit(captured["path"]).query)
    assert parsed.keys() == {"root_id", "limit"}
    assert parsed["root_id"] == ["root&child"]
    assert parsed["limit"] == ["7"]
    assert captured["method"] == "GET"
    assert captured["timeout"] == 0.5


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
        "runs": ["invalid"],
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
        "runs": [],
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
