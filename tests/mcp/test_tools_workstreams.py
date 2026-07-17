"""Tests for the create_workstream MCP tool orchestration (stubbed client)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import basecamp.claude.worktree as wt_mod
import basecamp.mcp.tools.workstreams as tool_mod
from basecamp.hub.claude.client.workstreams import WorkstreamCreateOutcome


def _init_repo(path: Path, origin: str = "https://github.com/acme/web-app.git") -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--initial-branch=main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.co"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True)
    (path / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=path, check=True)


class _StubClient:
    """Records calls and lets tests drive create/persist/delete outcomes."""

    def __init__(self, *, create_ok: bool = True) -> None:
        self.create_ok = create_ok
        self.persisted: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.DaemonError = RuntimeError

    def create_workstream(self, **kw):
        status = 201 if self.create_ok else 503
        return WorkstreamCreateOutcome(status=status, body=kw if self.create_ok else None)

    def set_workstream_worktree(self, wid, path):
        self.persisted.append((wid, path))
        return True

    def delete_workstream(self, wid):
        self.deleted.append(wid)
        return True


def _patch(monkeypatch, stub: _StubClient, *, home: Path) -> None:
    monkeypatch.setattr(tool_mod, "client", stub)
    orig = wt_mod.get_or_create_worktree
    monkeypatch.setattr(
        tool_mod.worktree,
        "get_or_create_worktree",
        lambda root, repo, label, branch: orig(root, repo, label, branch, home=home),
    )


def test_create_workstream_happy_path(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    home = tmp_path / "home"
    stub = _StubClient(create_ok=True)
    _patch(monkeypatch, stub, home=home)

    result = tool_mod.create_workstream(
        label="Auth Refactor",
        dossier_path="/g/pages/work__acme__web-app__x.md",
        cwd=str(repo),
        env={"USER": "btimothy"},  # no HERDR_* -> pane skips
    )

    assert result["status"] == "created"
    assert result["slug"]
    assert result["repo"] == "acme/web-app"
    assert result["worktree"]["label"] == f"copilot/{result['slug']}"
    assert result["worktree"]["branch"] == "bt/auth-refactor"
    assert Path(result["worktree"]["path"]).is_dir()
    # the worktree path was persisted (normalized) back onto the record
    assert stub.persisted and stub.persisted[0][1] == result["worktree"]["path"]
    # pane skipped (no Herdr env), record NOT rolled back
    assert result["pane"]["status"] == "skipped"
    assert stub.deleted == []


def test_create_workstream_rolls_back_on_worktree_failure(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    stub = _StubClient(create_ok=True)
    monkeypatch.setattr(tool_mod, "client", stub)

    def _boom(*_a, **_k):
        raise tool_mod.worktree.WorktreeError("boom")

    monkeypatch.setattr(tool_mod.worktree, "get_or_create_worktree", _boom)

    result = tool_mod.create_workstream(label="x", cwd=str(repo), env={"USER": "bt"})

    assert result["status"] == "failed"
    assert result["error"] == "worktree provisioning failed"
    # the record was created then rolled back
    assert len(stub.deleted) == 1


def test_create_workstream_not_a_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    result = tool_mod.create_workstream(label="x", cwd=str(plain), env={})
    assert result["status"] == "failed"
    assert result["error"] == "not a git repository"


def test_create_workstream_daemon_unavailable(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    stub = _StubClient(create_ok=False)  # create returns 503 -> not created
    monkeypatch.setattr(tool_mod, "client", stub)
    result = tool_mod.create_workstream(label="x", cwd=str(repo), env={"USER": "bt"})
    assert result["status"] == "failed"
    assert result["error"] == "slug allocation failed"
