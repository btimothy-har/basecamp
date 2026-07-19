"""Tests for the fail-open Claude Code lifecycle hooks."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

import basecamp.hooks as hooks
from basecamp.claude import launchcard
from basecamp.claude.launchcard import LaunchCard
from basecamp.hooks import session as session_mod


def _set_stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def _log_path(home: Path) -> Path:
    return home / ".pi" / "basecamp" / "claude" / "hooks.log"


@pytest.fixture(autouse=True)
def ingest_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Stub the transcript-ingest RPC so hook tests stay hermetic (no real socket).

    Autouse: SessionEnd/PreCompact now fire ``ingest_transcript`` and would
    otherwise attempt a real UDS connection. Tests that care read the recorder.
    """

    calls: list[dict[str, object]] = []

    def _record(session_id: str, **kwargs: object) -> bool:
        calls.append({"session_id": session_id, **kwargs})
        return True

    monkeypatch.setattr(session_mod, "ingest_transcript", _record)
    return calls


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


def test_session_start_normalizes_empty_string_fields_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # An empty source/transcript is treated as absent (NULL), not stored as "".
    bodies = []
    monkeypatch.setattr(session_mod, "register_session", bodies.append)

    session_mod.handle_session_start(
        {"session_id": "s1", "cwd": "/work", "transcript_path": "", "source": ""},
        env={"BASECAMP_REPO": "acme/widgets"},
    )

    assert bodies[0].source is None
    assert bodies[0].transcript_path is None


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


def test_session_start_returns_launch_card_for_bcc_session(monkeypatch: pytest.MonkeyPatch) -> None:
    # BASECAMP_BCC_LAUNCH marks a bcc-originated session: the handler returns the card
    # as a JSON systemMessage (user-facing), carrying the project identity.
    monkeypatch.setattr(session_mod, "register_session", lambda _body: None)
    card = LaunchCard(
        scratch_dir="/tmp/claude/acme/web", is_repo=True, projected=True, display_name="acme/web", branch="main"
    )
    monkeypatch.setattr(launchcard, "gather_launch_card", lambda *_a, **_k: card)

    out = session_mod.handle_session_start(
        {"session_id": "s1", "cwd": "/work", "source": "startup"},
        env={"BASECAMP_BCC_LAUNCH": "1", "BASECAMP_SCRATCH_DIR": "/tmp/claude/acme/web"},
    )

    assert out is not None
    assert "acme/web" in json.loads(out)["systemMessage"]


def test_session_start_no_launch_card_without_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    # A bare `claude` (no bcc marker) shows nothing — the gate short-circuits before gathering.
    monkeypatch.setattr(session_mod, "register_session", lambda _body: None)
    gathered: list[int] = []
    monkeypatch.setattr(launchcard, "gather_launch_card", lambda *_a, **_k: gathered.append(1))

    out = session_mod.handle_session_start({"session_id": "s1", "cwd": "/work", "source": "startup"}, env={})

    assert out is None
    assert gathered == []


def test_session_start_no_launch_card_on_compact(monkeypatch: pytest.MonkeyPatch) -> None:
    # A post-compaction restart must not re-spam the card, even for a bcc session.
    monkeypatch.setattr(session_mod, "register_session", lambda _body: None)
    gathered: list[int] = []
    monkeypatch.setattr(launchcard, "gather_launch_card", lambda *_a, **_k: gathered.append(1))

    out = session_mod.handle_session_start(
        {"session_id": "s1", "cwd": "/work", "source": "compact"},
        env={"BASECAMP_BCC_LAUNCH": "1"},
    )

    assert out is None
    assert gathered == []


def test_session_start_launch_card_is_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    # A card failure must never break session start: registration still happens, no output.
    bodies = []
    monkeypatch.setattr(session_mod, "register_session", bodies.append)

    def _boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(launchcard, "gather_launch_card", _boom)

    out = session_mod.handle_session_start(
        {"session_id": "s1", "cwd": "/work", "source": "startup"},
        env={"BASECAMP_BCC_LAUNCH": "1"},
    )

    assert out is None
    assert len(bodies) == 1
    assert bodies[0].session_id == "s1"


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


def test_session_end_normalizes_empty_reason_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    ended = []
    monkeypatch.setattr(session_mod, "end_session", lambda sid, *, reason=None: ended.append((sid, reason)))

    session_mod.handle_session_end({"session_id": "s1", "reason": ""})

    assert ended == [("s1", None)]


def test_session_end_skips_missing_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    ended = []
    monkeypatch.setattr(session_mod, "end_session", lambda sid, *, reason=None: ended.append((sid, reason)))

    session_mod.handle_session_end({})
    session_mod.handle_session_end({"session_id": ""})

    assert ended == []


def test_session_end_ingests_the_final_transcript_before_closing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ingest must run before the episode closes, with no path (daemon uses the stored
    # one) and reason "session-end", so tail nodes are tagged with the ending episode.
    events: list[tuple[str, str, object]] = []
    monkeypatch.setattr(
        session_mod,
        "ingest_transcript",
        lambda sid, **kwargs: events.append(("ingest", sid, kwargs.get("reason"))) or True,
    )
    monkeypatch.setattr(
        session_mod, "end_session", lambda sid, *, reason=None: events.append(("end", sid, reason)) or True
    )

    session_mod.handle_session_end({"session_id": "s1", "reason": "logout"})

    assert events == [("ingest", "s1", "session-end"), ("end", "s1", "logout")]


def test_session_end_requests_a_sidecar_sweep(
    monkeypatch: pytest.MonkeyPatch, ingest_calls: list[dict[str, object]]
) -> None:
    # SessionEnd is the guaranteed backstop: it sweeps every (now-complete) sidecar.
    monkeypatch.setattr(session_mod, "end_session", lambda _sid, **_kwargs: True)

    session_mod.handle_session_end({"session_id": "s1", "reason": "logout"})

    assert ingest_calls == [{"session_id": "s1", "reason": "session-end", "sweep_sidecars": True}]


# --- pre-compact handler ---------------------------------------------------------


def test_pre_compact_ingests_with_the_payload_transcript_path(ingest_calls: list[dict[str, object]]) -> None:
    session_mod.handle_pre_compact({"session_id": "s1", "transcript_path": "/t.jsonl"})

    assert ingest_calls == [{"session_id": "s1", "transcript_path": "/t.jsonl", "reason": "pre-compact"}]


def test_pre_compact_threads_absent_path_as_none(ingest_calls: list[dict[str, object]]) -> None:
    # An empty/absent path is normalized to None; the daemon falls back to the stored path.
    session_mod.handle_pre_compact({"session_id": "s1", "transcript_path": ""})

    assert ingest_calls == [{"session_id": "s1", "transcript_path": None, "reason": "pre-compact"}]


def test_pre_compact_skips_subagent(ingest_calls: list[dict[str, object]]) -> None:
    session_mod.handle_pre_compact({"session_id": "s1", "agent_type": "subagent", "transcript_path": "/t.jsonl"})

    assert ingest_calls == []


def test_pre_compact_skips_missing_session_id(ingest_calls: list[dict[str, object]]) -> None:
    session_mod.handle_pre_compact({"transcript_path": "/t.jsonl"})
    session_mod.handle_pre_compact({"session_id": "", "transcript_path": "/t.jsonl"})

    assert ingest_calls == []


def test_pre_compact_is_wired_into_the_dispatcher() -> None:
    assert hooks._load_handler("pre-compact") is session_mod.handle_pre_compact


# --- subagent-stop handler -------------------------------------------------------


def test_subagent_stop_targets_the_completed_sidecar(ingest_calls: list[dict[str, object]]) -> None:
    session_mod.handle_subagent_stop(
        {
            "session_id": "s1",
            "transcript_path": "/main.jsonl",
            "agent_transcript_path": "/main/subagents/agent-x.jsonl",
            "agent_id": "x",
        }
    )

    assert ingest_calls == [
        {
            "session_id": "s1",
            "transcript_path": "/main.jsonl",
            "agent_transcript_path": "/main/subagents/agent-x.jsonl",
            "reason": "subagent-stop",
        }
    ]


def test_subagent_stop_without_a_sidecar_path_is_noop(ingest_calls: list[dict[str, object]]) -> None:
    # No agent_transcript_path → nothing to target; the SessionEnd sweep is the backstop.
    session_mod.handle_subagent_stop({"session_id": "s1", "transcript_path": "/main.jsonl"})

    assert ingest_calls == []


def test_subagent_stop_skips_missing_session_id(ingest_calls: list[dict[str, object]]) -> None:
    session_mod.handle_subagent_stop({"agent_transcript_path": "/a.jsonl"})
    session_mod.handle_subagent_stop({"session_id": "", "agent_transcript_path": "/a.jsonl"})

    assert ingest_calls == []


def test_subagent_stop_is_wired_into_the_dispatcher() -> None:
    assert hooks._load_handler("subagent-stop") is session_mod.handle_subagent_stop
