"""Tests for the fail-open Claude Code lifecycle hooks."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

import basecamp.hooks as hooks
from basecamp.hooks import session as session_mod


def _set_stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def _log_path(home: Path) -> Path:
    return home / ".pi" / "basecamp" / "claude" / "hooks.log"


# --- main() dispatch (fail-open) -------------------------------------------------


def test_dispatch_routes_payload_to_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setitem(hooks._HANDLERS, "session-start", lambda payload: seen.update(payload))
    _set_stdin(monkeypatch, json.dumps({"session_id": "s1", "cwd": "/x"}))

    assert hooks.main(["session-start"]) == 0
    assert seen == {"session_id": "s1", "cwd": "/x"}


def test_unknown_event_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_stdin(monkeypatch, "{}")
    assert hooks.main(["totally-unknown"]) == 0


def test_missing_event_arg_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_stdin(monkeypatch, "{}")
    assert hooks.main([]) == 0


def test_empty_stdin_yields_empty_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setitem(hooks._HANDLERS, "session-end", lambda payload: captured.setdefault("p", payload))
    _set_stdin(monkeypatch, "   ")

    assert hooks.main(["session-end"]) == 0
    assert captured["p"] == {}


def test_handler_exception_is_swallowed_and_logged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    def boom(_payload: object) -> None:
        msg = "kaboom"
        raise RuntimeError(msg)

    monkeypatch.setitem(hooks._HANDLERS, "session-start", boom)
    _set_stdin(monkeypatch, json.dumps({"session_id": "s1"}))

    assert hooks.main(["session-start"]) == 0
    log = _log_path(tmp_path)
    assert log.exists()
    assert "kaboom" in log.read_text(encoding="utf-8")


def test_malformed_json_is_swallowed_and_handler_not_reached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    called: list[object] = []
    monkeypatch.setitem(hooks._HANDLERS, "session-start", called.append)
    _set_stdin(monkeypatch, "{not json")

    assert hooks.main(["session-start"]) == 0
    assert called == []
    assert _log_path(tmp_path).exists()


# --- session handlers ------------------------------------------------------------


def test_session_start_registers_valid_session(monkeypatch: pytest.MonkeyPatch) -> None:
    bodies = []
    monkeypatch.setattr(session_mod, "register_session", bodies.append)

    session_mod.handle_session_start(
        {"session_id": "s1", "cwd": "/work", "transcript_path": "/t.jsonl", "source": "startup"},
        env={"BASECAMP_REPO": "acme/widgets"},
    )

    assert len(bodies) == 1
    body = bodies[0]
    assert body.session_id == "s1"
    assert body.cwd == "/work"
    assert body.transcript_path == "/t.jsonl"
    assert body.repo == "acme/widgets"
    assert body.source == "startup"


def test_session_start_skips_subagent(monkeypatch: pytest.MonkeyPatch) -> None:
    called = []
    monkeypatch.setattr(session_mod, "register_session", called.append)

    session_mod.handle_session_start({"session_id": "s1", "agent_type": "subagent"}, env={})

    assert called == []


def test_session_start_skips_missing_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    called = []
    monkeypatch.setattr(session_mod, "register_session", called.append)

    session_mod.handle_session_start({"cwd": "/work"}, env={})
    session_mod.handle_session_start({"session_id": ""}, env={})
    session_mod.handle_session_start({"session_id": 123}, env={})

    assert called == []


def test_session_end_closes_the_current_episode(monkeypatch: pytest.MonkeyPatch) -> None:
    ended = []
    monkeypatch.setattr(session_mod, "end_session", lambda sid, *, reason=None: ended.append((sid, reason)))

    session_mod.handle_session_end({"session_id": "s1", "reason": "logout"})

    assert ended == [("s1", "logout")]


@pytest.mark.parametrize("reason", ["clear", "resume"])
def test_session_end_closes_episode_even_on_continuation_reasons(monkeypatch: pytest.MonkeyPatch, reason: str) -> None:
    # /clear and resume are no longer skipped: each fires a SessionEnd that closes
    # the current episode, and the paired SessionStart opens the next one.
    ended = []
    monkeypatch.setattr(session_mod, "end_session", lambda sid, *, reason=None: ended.append((sid, reason)))

    session_mod.handle_session_end({"session_id": "s1", "reason": reason})

    assert ended == [("s1", reason)]


def test_session_end_threads_absent_reason_as_none(monkeypatch: pytest.MonkeyPatch) -> None:
    ended = []
    monkeypatch.setattr(session_mod, "end_session", lambda sid, *, reason=None: ended.append((sid, reason)))

    session_mod.handle_session_end({"session_id": "s1"})

    assert ended == [("s1", None)]


def test_session_end_skips_missing_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    ended = []
    monkeypatch.setattr(session_mod, "end_session", lambda sid, *, reason=None: ended.append((sid, reason)))

    session_mod.handle_session_end({})
    session_mod.handle_session_end({"session_id": ""})

    assert ended == []
