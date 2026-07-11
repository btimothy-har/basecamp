"""Tests for the event-driven analysis scheduler."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from basecamp.swarm.analysis.scheduler import AnalysisScheduler
from basecamp.swarm.analysis.sections import AnalysisSections
from basecamp.swarm.store import Store
from basecamp.swarm.store.raw_pi_thread import RawPiThreadNode


class _FakeAnalyzer:
    """Records analyze calls and returns a fixed dashboard (no network)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.sections = AnalysisSections(monitor=["m"], needs_capture=[], checkpoints=[])

    async def analyze(self, *, context: str, already_tracked: str, prior: Any, model: str) -> AnalysisSections:
        self.calls.append({"context": context, "already_tracked": already_tracked, "prior": prior, "model": model})
        return self.sections


def _user_node(entry_id: str, parent_id: str | None, text: str) -> RawPiThreadNode:
    entry = {"id": entry_id, "parentId": parent_id, "type": "message", "message": {"role": "user", "content": text}}
    return RawPiThreadNode(entry_id=entry_id, parent_id=parent_id, entry_json=json.dumps(entry))


def _seed_thread(store: Store, owner_id: str, leaf: str, nodes: list[RawPiThreadNode]) -> int:
    return store.record_raw_pi_thread(owner_id=owner_id, session_id="pi", session_file=None, leaf_id=leaf, nodes=nodes)


async def _wait_for_analysis_seq(store: Store, owner_id: str, seq: int, *, max_wait: float = 2.0) -> Any:
    for _ in range(int(max_wait / 0.01)):
        row = await asyncio.to_thread(store.get_analysis, owner_id)
        if row is not None and row.based_on_thread_seq == seq:
            return row
        await asyncio.sleep(0.01)
    return None


def _scheduler(store: Store, analyzer: Any, *, model: str | None = "prov/m") -> AnalysisScheduler:
    # Single attempt, no backoff: these tests assert per-turn behavior, not the retry path.
    return AnalysisScheduler(
        store, analyzer=analyzer, model=model, debounce_seconds=0, max_attempts=1, retry_backoff_seconds=0.0
    )


@pytest.mark.asyncio
async def test_runs_analysis_on_a_fresh_turn(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "d.db")
    seq = _seed_thread(store, "s", "e1", [_user_node("e1", None, "hi there")])
    analyzer = _FakeAnalyzer()
    scheduler = _scheduler(store, analyzer)

    scheduler.notify("s", seq)
    row = await _wait_for_analysis_seq(store, "s", seq)

    assert row is not None
    assert row.based_on_thread_seq == seq
    assert row.model == "prov/m"
    assert len(analyzer.calls) == 1
    assert "hi there" in analyzer.calls[0]["context"]
    await scheduler.stop()


@pytest.mark.asyncio
async def test_coalesces_a_burst_into_the_latest(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "d.db")
    _seed_thread(store, "s", "e1", [_user_node("e1", None, "first")])
    analyzer = _FakeAnalyzer()
    scheduler = _scheduler(store, analyzer)

    # Two synchronous notifies (no await between) land before the worker runs.
    scheduler.notify("s", 1)
    seq2 = _seed_thread(store, "s", "e2", [_user_node("e2", "e1", "second")])
    scheduler.notify("s", seq2)

    row = await _wait_for_analysis_seq(store, "s", seq2)

    assert row is not None
    assert row.based_on_thread_seq == seq2
    assert len(analyzer.calls) == 1  # coalesced to a single run on the latest
    await scheduler.stop()


@pytest.mark.asyncio
async def test_does_not_rerun_when_seq_has_not_advanced(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "d.db")
    seq = _seed_thread(store, "s", "e1", [_user_node("e1", None, "hi")])
    analyzer = _FakeAnalyzer()
    scheduler = _scheduler(store, analyzer)

    scheduler.notify("s", seq)
    await _wait_for_analysis_seq(store, "s", seq)
    scheduler.notify("s", seq)  # same seq — nothing fresh
    await asyncio.sleep(0.05)

    assert len(analyzer.calls) == 1
    await scheduler.stop()


@pytest.mark.asyncio
async def test_seeds_last_analyzed_from_the_persisted_row(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "d.db")
    _seed_thread(store, "s", "e1", [_user_node("e1", None, "hi")])
    store.record_analysis(owner_id="s", based_on_thread_seq=5, model="old", sections_json='{"monitor":["old"]}')
    analyzer = _FakeAnalyzer()
    scheduler = _scheduler(store, analyzer)

    scheduler.notify("s", 3)  # stale relative to the seeded seq 5
    await asyncio.sleep(0.05)
    assert analyzer.calls == []

    scheduler.notify("s", 6)  # genuinely fresh
    row = await _wait_for_analysis_seq(store, "s", 6)

    assert row is not None
    assert row.based_on_thread_seq == 6
    assert len(analyzer.calls) == 1
    await scheduler.stop()


@pytest.mark.asyncio
async def test_skips_when_no_model_configured(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "d.db")
    seq = _seed_thread(store, "s", "e1", [_user_node("e1", None, "hi")])
    analyzer = _FakeAnalyzer()
    scheduler = _scheduler(store, analyzer, model=None)

    scheduler.notify("s", seq)
    await asyncio.sleep(0.05)

    assert analyzer.calls == []
    assert store.get_analysis("s") is None
    await scheduler.stop()


@pytest.mark.asyncio
async def test_analyzer_error_does_not_kill_the_worker(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "d.db")

    class _FlakyAnalyzer:
        def __init__(self) -> None:
            self.calls = 0

        async def analyze(self, *, context: str, already_tracked: str, prior: Any, model: str) -> AnalysisSections:  # noqa: ARG002
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            return AnalysisSections(monitor=["recovered"], needs_capture=[], checkpoints=[])

    analyzer = _FlakyAnalyzer()
    scheduler = AnalysisScheduler(
        store, analyzer=analyzer, model="m", debounce_seconds=0, max_attempts=1, retry_backoff_seconds=0.0
    )

    _seed_thread(store, "s", "e1", [_user_node("e1", None, "first")])
    scheduler.notify("s", 1)
    await asyncio.sleep(0.05)
    assert store.get_analysis("s") is None  # first run failed, nothing recorded

    seq2 = _seed_thread(store, "s", "e2", [_user_node("e2", "e1", "second")])
    scheduler.notify("s", seq2)
    row = await _wait_for_analysis_seq(store, "s", seq2)

    assert row is not None
    assert analyzer.calls == 2  # worker survived the error and ran again
    await scheduler.stop()


@pytest.mark.asyncio
async def test_retries_a_transient_failure_within_the_same_turn(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "d.db")
    seq = _seed_thread(store, "s", "e1", [_user_node("e1", None, "hi")])

    class _FailOnce:
        def __init__(self) -> None:
            self.calls = 0

        async def analyze(self, *, context: str, already_tracked: str, prior: Any, model: str) -> AnalysisSections:  # noqa: ARG002
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            return AnalysisSections(monitor=["ok"], needs_capture=[], checkpoints=[])

    analyzer = _FailOnce()
    scheduler = AnalysisScheduler(
        store, analyzer=analyzer, model="m", debounce_seconds=0, max_attempts=3, retry_backoff_seconds=0.0
    )

    scheduler.notify("s", seq)
    row = await _wait_for_analysis_seq(store, "s", seq)

    assert row is not None  # recovered via retry, no fresh turn needed
    assert analyzer.calls == 2
    await scheduler.stop()


@pytest.mark.asyncio
async def test_times_out_a_hung_analyzer_and_survives(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "d.db")
    seq = _seed_thread(store, "s", "e1", [_user_node("e1", None, "hi")])

    class _HangsThenOk:
        def __init__(self) -> None:
            self.calls = 0

        async def analyze(self, *, context: str, already_tracked: str, prior: Any, model: str) -> AnalysisSections:  # noqa: ARG002
            self.calls += 1
            if self.calls == 1:
                await asyncio.Event().wait()  # never returns → must time out
            return AnalysisSections(monitor=["ok"], needs_capture=[], checkpoints=[])

    analyzer = _HangsThenOk()
    scheduler = AnalysisScheduler(
        store,
        analyzer=analyzer,
        model="m",
        debounce_seconds=0,
        timeout_seconds=0.02,
        max_attempts=1,
        retry_backoff_seconds=0.0,
    )

    scheduler.notify("s", seq)
    await asyncio.sleep(0.1)
    assert store.get_analysis("s") is None  # hung run timed out, nothing recorded
    assert analyzer.calls == 1

    seq2 = _seed_thread(store, "s", "e2", [_user_node("e2", "e1", "more")])
    scheduler.notify("s", seq2)
    row = await _wait_for_analysis_seq(store, "s", seq2)

    assert row is not None  # worker survived the timeout and analyzed the next turn
    assert analyzer.calls == 2
    await scheduler.stop()
