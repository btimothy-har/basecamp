"""Tests for the create_workstream MCP tool orchestration (stubbed client)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx

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
    """Records calls and lets tests drive create/delete outcomes + failure modes."""

    def __init__(self, *, create_status: int = 201, raise_create: Exception | None = None, delete_ok: bool = True):
        self.create_status = create_status
        self.raise_create = raise_create
        self.delete_ok = delete_ok
        self.deleted: list[str] = []
        self.DaemonError = RuntimeError

    def create_workstream(self, **kw):
        if self.raise_create is not None:
            raise self.raise_create
        body = kw if self.create_status == 201 else None
        return WorkstreamCreateOutcome(status=self.create_status, body=body)

    def delete_workstream(self, wid):
        self.deleted.append(wid)
        return self.delete_ok


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
    stub = _StubClient()
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
    # branch derives from the unique SLUG, not the human label — so two similarly
    # titled workstreams never collide on an already-checked-out branch.
    assert result["worktree"]["branch"] == f"bt/{result['slug']}"
    assert Path(result["worktree"]["path"]).is_dir()
    # pane skipped (no Herdr env), record NOT rolled back
    assert result["pane"]["status"] == "skipped"
    assert stub.deleted == []


def test_create_workstream_rolls_back_on_worktree_failure(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    stub = _StubClient()
    monkeypatch.setattr(tool_mod, "client", stub)

    def _boom(*_a, **_k):
        raise tool_mod.worktree.WorktreeError("boom")

    monkeypatch.setattr(tool_mod.worktree, "get_or_create_worktree", _boom)

    result = tool_mod.create_workstream(label="x", cwd=str(repo), env={"USER": "bt"})

    assert result["status"] == "failed"
    assert result["error"] == "worktree provisioning failed"
    # the record was created then rolled back
    assert len(stub.deleted) == 1
    assert "manual cleanup" not in result["message"]  # rollback succeeded


def test_create_workstream_surfaces_orphan_when_rollback_fails(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    stub = _StubClient(delete_ok=False)  # rollback delete also fails
    monkeypatch.setattr(tool_mod, "client", stub)

    def _boom(*_a, **_k):
        raise tool_mod.worktree.WorktreeError("boom")

    monkeypatch.setattr(tool_mod.worktree, "get_or_create_worktree", _boom)

    result = tool_mod.create_workstream(label="x", cwd=str(repo), env={"USER": "bt"})
    assert result["status"] == "failed"
    # the orphaned (slug-consuming) record is surfaced, not silently reported as clean
    assert "manual cleanup" in result["message"]


def test_create_workstream_not_a_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    result = tool_mod.create_workstream(label="x", cwd=str(plain), env={})
    assert result["status"] == "failed"
    assert result["error"] == "not a git repository"


def test_create_workstream_transport_error_is_daemon_unavailable(monkeypatch, tmp_path: Path) -> None:
    # create raises an httpx transport error (daemon died after the health probe)
    repo = tmp_path / "repo"
    _init_repo(repo)
    stub = _StubClient(raise_create=httpx.ConnectError("boom"))
    monkeypatch.setattr(tool_mod, "client", stub)
    result = tool_mod.create_workstream(label="x", cwd=str(repo), env={"USER": "bt"})
    assert result["status"] == "failed"
    assert result["error"] == "daemon unavailable"  # not a raw traceback


def test_create_workstream_503_is_daemon_error_not_slug(monkeypatch, tmp_path: Path) -> None:
    # a transient store-busy 503 must NOT be misreported as slug exhaustion
    repo = tmp_path / "repo"
    _init_repo(repo)
    stub = _StubClient(create_status=503)
    monkeypatch.setattr(tool_mod, "client", stub)
    result = tool_mod.create_workstream(label="x", cwd=str(repo), env={"USER": "bt"})
    assert result["status"] == "failed"
    assert result["error"] == "daemon error"


def test_create_workstream_slug_exhaustion(monkeypatch, tmp_path: Path) -> None:
    # every attempt collides (409) -> genuine slug allocation failure
    repo = tmp_path / "repo"
    _init_repo(repo)
    stub = _StubClient(create_status=409)
    monkeypatch.setattr(tool_mod, "client", stub)
    result = tool_mod.create_workstream(label="x", cwd=str(repo), env={"USER": "bt"})
    assert result["status"] == "failed"
    assert result["error"] == "slug allocation failed"
