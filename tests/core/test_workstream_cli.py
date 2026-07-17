"""Tests for the `basecamp workstream current` CLI command."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

import basecamp.core.cli.workstream_group as wg
from basecamp.core.cli.workstream_group import workstream


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_current_prints_label_and_dossier(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wg, "_current_worktree_path", lambda: "/wt/copilot/a-b-c")
    monkeypatch.setattr(
        wg.client,
        "get_workstream_by_worktree",
        lambda _path: {
            "id": "ws_1",
            "slug": "brave-otter-fox",
            "label": "auth refactor",
            "dossier_path": "/g/pages/work__acme__web-app__brave-otter-fox.md",
        },
    )
    result = runner.invoke(workstream, ["current"])
    assert result.exit_code == 0
    assert "label: auth refactor" in result.output
    assert "slug: brave-otter-fox" in result.output
    assert "dossier: /g/pages/work__acme__web-app__brave-otter-fox.md" in result.output


def test_current_falls_back_to_slug_label(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wg, "_current_worktree_path", lambda: "/wt/x")
    monkeypatch.setattr(
        wg.client,
        "get_workstream_by_worktree",
        lambda _path: {"slug": "brave-otter-fox", "label": None, "dossier_path": None},
    )
    result = runner.invoke(workstream, ["current"])
    assert result.exit_code == 0
    assert "label: brave-otter-fox" in result.output  # falls back to slug
    assert "dossier: " in result.output  # empty dossier line still printed


def test_current_not_in_worktree_exits_1(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wg, "_current_worktree_path", lambda: None)
    result = runner.invoke(workstream, ["current"])
    assert result.exit_code != 0
    assert "not inside a git worktree" in result.output


def test_current_no_record_exits_1(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wg, "_current_worktree_path", lambda: "/wt/x")
    monkeypatch.setattr(wg.client, "get_workstream_by_worktree", lambda _path: None)
    result = runner.invoke(workstream, ["current"])
    assert result.exit_code != 0
    assert "no workstream is registered" in result.output
