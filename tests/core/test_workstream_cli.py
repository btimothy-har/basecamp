"""Tests for the `basecamp workstream` CLI commands (current + show)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

import basecamp.core.cli.workstream_group as wg
from basecamp.core.cli.workstream_group import workstream


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


_RECORD = {
    "id": "ws_1",
    "slug": "brave-otter-fox",
    "label": "auth refactor",
    "status": "open",
    "repo": "acme/web-app",
    "worktree_path": "/wt/copilot/brave-otter-fox",
    "dossier_path": "/g/pages/work__acme__web-app__brave-otter-fox.md",
}


def test_current_prints_pointers(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wg, "_current_worktree_path", lambda: "/wt/copilot/brave-otter-fox")
    monkeypatch.setattr(wg.client, "get_workstream_by_worktree", lambda _p: _RECORD)
    result = runner.invoke(workstream, ["current"])
    assert result.exit_code == 0
    assert "label: auth refactor" in result.output
    assert "repo: acme/web-app" in result.output
    assert "worktree: /wt/copilot/brave-otter-fox" in result.output
    assert "dossier: /g/pages/work__acme__web-app__brave-otter-fox.md" in result.output


def test_current_not_in_worktree_exits_1(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wg, "_current_worktree_path", lambda: None)
    result = runner.invoke(workstream, ["current"])
    assert result.exit_code != 0
    assert "not inside a git worktree" in result.output


def test_current_no_record_exits_1(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wg, "_current_worktree_path", lambda: "/wt/x")
    monkeypatch.setattr(wg.client, "get_workstream_by_worktree", lambda _p: None)
    result = runner.invoke(workstream, ["current"])
    assert result.exit_code != 0
    assert "no workstream is registered" in result.output


def test_show_by_slug_from_anywhere(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def _get(identifier: str) -> dict:
        seen.append(identifier)
        return _RECORD

    monkeypatch.setattr(wg.client, "get_workstream", _get)
    result = runner.invoke(workstream, ["show", "brave-otter-fox"])
    assert result.exit_code == 0
    assert seen == ["brave-otter-fox"]  # resolved by slug, no worktree inference
    assert "repo: acme/web-app" in result.output
    assert "dossier: /g/pages/work__acme__web-app__brave-otter-fox.md" in result.output


def test_show_unknown_exits_1(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wg.client, "get_workstream", lambda _i: None)
    result = runner.invoke(workstream, ["show", "nope-nope-nope"])
    assert result.exit_code != 0
    assert "no workstream found" in result.output


def test_show_falls_back_to_slug_label(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        wg.client,
        "get_workstream",
        lambda _i: {"slug": "brave-otter-fox", "label": None, "repo": "acme/web-app"},
    )
    result = runner.invoke(workstream, ["show", "brave-otter-fox"])
    assert result.exit_code == 0
    assert "label: brave-otter-fox" in result.output  # falls back to slug
