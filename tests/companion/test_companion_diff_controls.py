"""Companion diff density, layout, and render-cache tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from test_companion_app import _build_repo, _write_snapshot
from textual.widgets import Static

from basecamp.companion.app import CompanionApp
from basecamp.companion.delta_render import delta_path
from basecamp.companion.diff import DiffLine
from basecamp.companion.ui.diff import DiffBody, DiffView, FileList


def test_diff_bindings_are_scoped_to_diff_body() -> None:
    diff_keys = {binding.key for binding in DiffBody.BINDINGS}
    app_keys = {binding.key for binding in CompanionApp.BINDINGS}

    assert {"left", "right", "c", "l", "d"}.issubset(diff_keys)
    assert {"left", "right", "c", "l", "d"}.isdisjoint(app_keys)


def test_density_and_layout_toggles_cover_all_combinations(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")
    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            diff_view = app.query_one("#diff-view", DiffView)

            full_split = diff_view._last_signature
            assert full_split is not None
            assert full_split[-1] == ("full", "split")
            assert str(diff_view.border_title) == "Diff · all · full · split"

            await pilot.press("c")
            await pilot.pause(0.1)
            compact_split = diff_view._last_signature
            assert compact_split is not None
            assert compact_split[-1] == ("compact", "split")
            assert 0 < len(compact_split[3]) < len(full_split[3])
            assert str(diff_view.border_title) == "Diff · all · compact · split"

            await pilot.press("l")
            await pilot.pause(0.1)
            compact_stacked = diff_view._last_signature
            assert compact_stacked is not None
            assert compact_stacked[-1] == ("compact", "stacked")
            assert compact_stacked != compact_split
            assert str(diff_view.border_title) == "Diff · all · compact · stacked"

            await pilot.press("c")
            await pilot.pause(0.1)
            full_stacked = diff_view._last_signature
            assert full_stacked is not None
            assert full_stacked[-1] == ("full", "stacked")
            assert len(full_stacked[3]) > len(compact_stacked[3])

            await pilot.press("l")
            await pilot.pause(0.1)
            assert diff_view._last_signature == full_split
            assert str(diff_view.border_title) == "Diff · all · full · split"

    asyncio.run(run())


def test_diff_pane_renders_delta_layouts_when_available(tmp_path: Path) -> None:
    if delta_path() is None:
        pytest.skip("delta binary not installed")

    repo = tmp_path / "repo"
    snapshot_path = tmp_path / "snapshot.json"
    _build_repo(repo)
    _write_snapshot(snapshot_path, session_id="abcd-1234-5678-90ef")
    app = CompanionApp(snapshot_path=snapshot_path, cwd=repo)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            file_list = app.query_one("#file-list", FileList)
            for _ in range(6):
                if file_list.selected_file and file_list.selected_file.path == "b_small.txt":
                    break
                await pilot.press("right")
                await pilot.pause(0.1)

            split_content = str(app.query_one("#diff-content", Static).render())
            assert any(line.count("small") == 2 for line in split_content.splitlines())

            await pilot.press("l")
            await pilot.pause(0.1)
            stacked_content = str(app.query_one("#diff-content", Static).render())
            assert all(line.count("small") < 2 for line in stacked_content.splitlines())

    asyncio.run(run())


def test_diff_signature_tracks_width_and_render_key() -> None:
    view = DiffView()
    lines = [DiffLine(kind="added", text="x", line_no=1)]

    split_w80 = view._signature("f.py", "", lines, width=80, render_key=("full", "split"))
    split_w120 = view._signature("f.py", "", lines, width=120, render_key=("full", "split"))
    stacked_w80 = view._signature("f.py", "", lines, width=80, render_key=("full", "stacked"))

    assert split_w80 != split_w120
    assert split_w80 != stacked_w80
