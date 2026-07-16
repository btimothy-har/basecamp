"""Tests for the daemon-side transcript ingest service and scheduler."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from basecamp.hub.claude.ingest import IngestScheduler, ingest_session
from basecamp.hub.claude.store import SessionStore


def _transcript(path: Path, *uuids: str) -> Path:
    lines = [json.dumps({"uuid": u, "parentUuid": None, "type": "user", "timestamp": u}) for u in uuids]
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


def _sidecar(main: Path, agent_id: str, *uuids: str, tool_use_id: str | None = None) -> Path:
    """Write an ``agent-<id>.jsonl`` sidecar (+ optional ``.meta.json``) for ``main``."""

    root = main.with_suffix("") / "subagents"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"agent-{agent_id}.jsonl"
    lines = [
        json.dumps({"uuid": u, "parentUuid": None, "type": "assistant", "isSidechain": True, "timestamp": u})
        for u in uuids
    ]
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    if tool_use_id is not None:
        (root / f"agent-{agent_id}.meta.json").write_text(json.dumps({"toolUseId": tool_use_id}), encoding="utf-8")
    return path


# --- ingest_session (pure, synchronous) -----------------------------------------


def test_ingest_session_parses_and_records(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")
    transcript = _transcript(tmp_path / "t.jsonl", "a", "b", "c")

    count = ingest_session(store, session_id="s1", transcript_path=str(transcript), episode_id="e1")

    assert count == 3
    assert store.count_transcript_nodes("s1") == 3


def test_ingest_session_is_idempotent(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")
    transcript = _transcript(tmp_path / "t.jsonl", "a", "b")

    assert ingest_session(store, session_id="s1", transcript_path=str(transcript), episode_id="e1") == 2
    assert ingest_session(store, session_id="s1", transcript_path=str(transcript), episode_id="e1") == 0
    assert store.count_transcript_nodes("s1") == 2


def test_ingest_session_missing_file_returns_zero(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")

    count = ingest_session(store, session_id="s1", transcript_path=str(tmp_path / "nope.jsonl"), episode_id=None)

    assert count == 0
    assert store.count_transcript_nodes() == 0


# --- subagent sidecars ----------------------------------------------------------


def _agent_ids(store: SessionStore, session_id: str) -> dict[str, str | None]:
    """Map each stored node's uuid to its ``source_agent_id`` for ``session_id``."""

    with store._connect() as connection:  # noqa: SLF001 - test reaches into the store's DB
        rows = connection.execute(
            "SELECT uuid, source_agent_id, source_tool_use_id FROM transcript_nodes WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}


def test_ingest_session_sweeps_sidecars_and_stamps_linkage(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")
    main = _transcript(tmp_path / "t.jsonl", "m1", "m2")
    _sidecar(main, "alpha", "x1", "x2", tool_use_id="toolu_alpha")
    _sidecar(main, "beta", "y1", tool_use_id="toolu_beta")

    count = ingest_session(store, session_id="s1", transcript_path=str(main), episode_id="e1", sweep_sidecars=True)

    assert count == 5
    rows = _agent_ids(store, "s1")
    assert rows["m1"] == (None, None)  # main-thread nodes carry no linkage
    assert rows["x1"] == ("alpha", "toolu_alpha")
    assert rows["y1"] == ("beta", "toolu_beta")


def test_ingest_session_without_sweep_ignores_sidecars(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")
    main = _transcript(tmp_path / "t.jsonl", "m1")
    _sidecar(main, "alpha", "x1", tool_use_id="toolu_alpha")

    count = ingest_session(store, session_id="s1", transcript_path=str(main), episode_id="e1")

    assert count == 1
    assert store.count_transcript_nodes("s1") == 1


def test_ingest_session_targeted_sidecar_only(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")
    main = _transcript(tmp_path / "t.jsonl", "m1", "m2")
    sidecar = _sidecar(main, "alpha", "x1", "x2", tool_use_id="toolu_alpha")

    count = ingest_session(
        store, session_id="s1", transcript_path=str(main), episode_id="e1", agent_transcript_path=str(sidecar)
    )

    # Only the one sidecar's nodes — the main file is ingested by its own triggers.
    assert count == 2
    assert store.has_agent_nodes("s1", "alpha") is True
    rows = _agent_ids(store, "s1")
    assert set(rows) == {"x1", "x2"}


def test_ingest_session_sweep_skips_already_stored_sidecar(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")
    main = _transcript(tmp_path / "t.jsonl", "m1")
    sidecar = _sidecar(main, "alpha", "x1", "x2", tool_use_id="toolu_alpha")

    # SubagentStop stored alpha; the SessionEnd sweep must not re-count it.
    ingest_session(
        store, session_id="s1", transcript_path=str(main), episode_id="e1", agent_transcript_path=str(sidecar)
    )
    swept = ingest_session(store, session_id="s1", transcript_path=str(main), episode_id="e1", sweep_sidecars=True)

    assert swept == 1  # only the main file's node was new
    assert store.count_transcript_nodes("s1") == 3


def test_ingest_session_no_main_path_no_sidecar_returns_zero(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")

    count = ingest_session(store, session_id="s1", transcript_path=None, episode_id=None)

    assert count == 0
    assert store.count_transcript_nodes() == 0


# --- IngestScheduler (fire-and-forget) ------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_runs_ingest_in_the_background(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")
    transcript = _transcript(tmp_path / "t.jsonl", "a", "b")
    scheduler = IngestScheduler(store)

    scheduler.schedule(session_id="s1", transcript_path=str(transcript), episode_id="e1")
    await scheduler.drain()

    assert store.count_transcript_nodes("s1") == 2


@pytest.mark.asyncio
async def test_scheduler_passes_resolved_args_to_the_ingest_fn(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def _fake_ingest(_store: object, **kwargs: object) -> int:
        calls.append(kwargs)
        return 0

    scheduler = IngestScheduler(SessionStore(db_path=tmp_path / "daemon.db"), ingest=_fake_ingest)

    scheduler.schedule(session_id="s1", transcript_path="/t.jsonl", episode_id="e1", agent_transcript_path="/a.jsonl")
    await scheduler.drain()

    assert calls == [
        {
            "session_id": "s1",
            "transcript_path": "/t.jsonl",
            "episode_id": "e1",
            "sweep_sidecars": False,
            "agent_transcript_path": "/a.jsonl",
        }
    ]


@pytest.mark.asyncio
async def test_scheduler_swallows_ingest_errors(tmp_path: Path) -> None:
    def _boom(*_args: object, **_kwargs: object) -> int:
        msg = "kaboom"
        raise RuntimeError(msg)

    scheduler = IngestScheduler(SessionStore(db_path=tmp_path / "daemon.db"), ingest=_boom)

    scheduler.schedule(session_id="s1", transcript_path="/t.jsonl", episode_id=None)

    # A failing ingest must not surface out of the background task or leave it pending.
    await scheduler.drain()
