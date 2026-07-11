"""Tests for the latest-only ``analysis`` store."""

from __future__ import annotations

from pathlib import Path

from basecamp.swarm.store import Store


def test_record_then_get_latest_analysis(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    store.record_analysis(
        owner_id="s",
        based_on_thread_seq=3,
        model="alias/model-x",
        sections_json='{"monitor":["a"]}',
    )

    row = store.get_analysis("s")
    assert row is not None
    assert row.owner_id == "s"
    assert row.based_on_thread_seq == 3
    assert row.model == "alias/model-x"
    assert row.sections_json == '{"monitor":["a"]}'
    assert row.updated_at


def test_record_upserts_latest_only(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    store.record_analysis(owner_id="s", based_on_thread_seq=1, model="m1", sections_json='{"monitor":["old"]}')
    store.record_analysis(owner_id="s", based_on_thread_seq=4, model="m2", sections_json='{"monitor":["new"]}')

    row = store.get_analysis("s")
    assert row is not None
    assert row.based_on_thread_seq == 4
    assert row.model == "m2"
    assert row.sections_json == '{"monitor":["new"]}'


def test_missing_analysis_returns_none(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    assert store.get_analysis("nobody") is None
