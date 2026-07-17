"""Tests for the `basecamp workstream` CLI commands (current + show + attach)."""

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
    "live": 1,
    "repo": "acme/web-app",
    "dossier_path": "/g/pages/work__acme__web-app__brave-otter-fox.md",
}


def test_current_derives_slug_from_worktree_path(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    # a copilot/<slug> worktree path -> slug -> get_workstream(slug)
    monkeypatch.setattr(wg, "_worktree_toplevel", lambda: "/home/u/.worktrees/acme/web-app/copilot/brave-otter-fox")
    seen: list[str] = []

    def _get(identifier: str) -> dict:
        seen.append(identifier)
        return _RECORD

    monkeypatch.setattr(wg.client, "get_workstream", _get)
    result = runner.invoke(workstream, ["current"])
    assert result.exit_code == 0
    assert seen == ["brave-otter-fox"]  # slug pulled from the path, looked up by slug
    assert "label: auth refactor" in result.output
    assert "dossier: /g/pages/work__acme__web-app__brave-otter-fox.md" in result.output


def test_current_not_in_workstream_worktree_exits_1(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    # a plain repo path (no copilot/<slug> segment)
    monkeypatch.setattr(wg, "_worktree_toplevel", lambda: "/home/u/code/some-repo")
    result = runner.invoke(workstream, ["current"])
    assert result.exit_code != 0
    assert "not inside a workstream worktree" in result.output


def test_current_slug_immune_to_copilot_earlier_in_path(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    # a 'copilot' username/org earlier in the path must NOT hijack the slug — only the
    # trailing copilot/<slug> segment counts.
    monkeypatch.setattr(wg, "_worktree_toplevel", lambda: "/Users/copilot/.worktrees/acme/web/copilot/brave-otter-fox")
    seen: list[str] = []
    monkeypatch.setattr(wg.client, "get_workstream", lambda i: (seen.append(i), _RECORD)[1])
    result = runner.invoke(workstream, ["current"])
    assert result.exit_code == 0
    assert seen == ["brave-otter-fox"]  # the trailing slug, not '.worktrees'


def test_show_by_slug_from_anywhere(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def _get(identifier: str) -> dict:
        seen.append(identifier)
        return _RECORD

    monkeypatch.setattr(wg.client, "get_workstream", _get)
    result = runner.invoke(workstream, ["show", "brave-otter-fox"])
    assert result.exit_code == 0
    assert seen == ["brave-otter-fox"]
    assert "repo: acme/web-app" in result.output


def test_show_unknown_exits_1(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wg.client, "get_workstream", lambda _i: None)
    result = runner.invoke(workstream, ["show", "nope-nope-nope"])
    assert result.exit_code != 0
    assert "no workstream found" in result.output


def test_attach_uses_session_id_from_env(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-123")
    monkeypatch.setattr(wg, "repo_identity", lambda _cwd: "acme/web-app")
    monkeypatch.setattr(wg, "_worktree_toplevel", lambda: "/wt/copilot/brave-otter-fox")
    calls: list[tuple] = []

    def _attach(identifier, session_id, *, repo=None, worktree_path=None):
        calls.append((identifier, session_id, repo, worktree_path))
        return True

    monkeypatch.setattr(wg.client, "attach_workstream_session", _attach)
    result = runner.invoke(workstream, ["attach", "brave-otter-fox"])
    assert result.exit_code == 0
    assert calls == [("brave-otter-fox", "sess-123", "acme/web-app", "/wt/copilot/brave-otter-fox")]
    assert "attached to brave-otter-fox" in result.output


def test_attach_without_session_id_exits_1(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    result = runner.invoke(workstream, ["attach", "brave-otter-fox"])
    assert result.exit_code != 0
    assert "no CLAUDE_CODE_SESSION_ID" in result.output


def test_attach_unknown_workstream_exits_1(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-123")
    monkeypatch.setattr(wg, "repo_identity", lambda _cwd: None)
    monkeypatch.setattr(wg, "_worktree_toplevel", lambda: None)
    monkeypatch.setattr(wg.client, "attach_workstream_session", lambda *_a, **_k: False)
    result = runner.invoke(workstream, ["attach", "nope"])
    assert result.exit_code != 0
    assert "could not attach" in result.output
