"""Tests for basecamp.claude.herdr — the pane-open eligibility predicate + args."""

from __future__ import annotations

import basecamp.claude.herdr as herdr_mod
from basecamp.claude.herdr import build_open_args, herdr_skip_reason, open_pane

_FULL_ENV = {
    "HERDR_ENV": "1",
    "HERDR_SOCKET_PATH": "/tmp/herdr.sock",
    "HERDR_PANE_ID": "wE:p1",
    "HERDR_WORKSPACE_ID": "wE",
}


def test_skip_reason_when_not_in_herdr() -> None:
    assert herdr_skip_reason({}) == "missing-herdr-env"
    assert herdr_skip_reason({"HERDR_ENV": "1"}) == "missing-herdr-socket-path"
    assert herdr_skip_reason({"HERDR_ENV": "1", "HERDR_SOCKET_PATH": "/s"}) == "missing-herdr-pane-id"


def test_skip_reason_subagent_and_headless() -> None:
    assert herdr_skip_reason({**_FULL_ENV, "BASECAMP_AGENT_DEPTH": "1"}) == "subagent"
    assert herdr_skip_reason(_FULL_ENV, has_ui=False) == "headless"


def test_skip_reason_none_when_eligible() -> None:
    assert herdr_skip_reason(_FULL_ENV) is None
    # empty/absent depth counts as primary (0)
    assert herdr_skip_reason({**_FULL_ENV, "BASECAMP_AGENT_DEPTH": ""}) is None


def test_build_open_args_prefers_workspace() -> None:
    args = build_open_args(worktree_path="/wt/x", label="copilot/a-b-c", workspace_cwd="/repo", env=_FULL_ENV)
    assert args == [
        "worktree",
        "open",
        "--workspace",
        "wE",
        "--path",
        "/wt/x",
        "--label",
        "copilot/a-b-c",
        "--no-focus",
        "--json",
    ]


def test_build_open_args_falls_back_to_cwd() -> None:
    env = {k: v for k, v in _FULL_ENV.items() if k != "HERDR_WORKSPACE_ID"}
    args = build_open_args(worktree_path="/wt/x", label="copilot/a-b-c", workspace_cwd="/repo", env=env)
    assert "--cwd" in args and "/repo" in args
    # no workspace id and no cwd -> None
    assert build_open_args(worktree_path="/wt/x", label="l", workspace_cwd=None, env=env) is None


def test_open_pane_skips_outside_herdr() -> None:
    result = open_pane(worktree_path="/wt/x", label="copilot/a-b-c", workspace_cwd="/repo", env={})
    assert result.status == "skipped"
    assert result.reason == "missing-herdr-env"


def test_open_pane_tolerates_missing_binary(monkeypatch) -> None:
    # eligible env but herdr not on PATH -> skipped, never raises
    def _boom(*_a, **_k):
        raise FileNotFoundError("herdr")

    monkeypatch.setattr(herdr_mod.subprocess, "run", _boom)
    result = open_pane(worktree_path="/wt/x", label="copilot/a-b-c", workspace_cwd="/repo", env=_FULL_ENV)
    assert result.status == "skipped"
    assert result.reason == "no-herdr"


def test_open_pane_reports_nonzero_exit(monkeypatch) -> None:
    class _Proc:
        returncode = 3

    monkeypatch.setattr(herdr_mod.subprocess, "run", lambda *_a, **_k: _Proc())
    result = open_pane(worktree_path="/wt/x", label="copilot/a-b-c", workspace_cwd="/repo", env=_FULL_ENV)
    assert result.status == "failed"
