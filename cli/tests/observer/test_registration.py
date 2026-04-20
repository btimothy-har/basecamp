"""Tests for the registration service."""

import subprocess
from datetime import UTC, datetime
from unittest.mock import patch

import observer.services.registration as reg
import pytest
from observer.data.transcript import Transcript
from observer.exceptions import RegistrationError
from observer.services.db import Database
from observer.services.registration import (
    HookInput,
    detect_worktree,
    register_session,
    resolve_repo_root,
)


class TestResolveRepoRoot:
    def test_valid_repo(self, tmp_path):  # noqa: ARG002
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        result = resolve_repo_root(str(tmp_path))
        assert result is not None
        assert result == tmp_path.resolve()

    def test_not_a_repo(self):
        failed = subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="")
        with patch("observer.services.registration.subprocess.run", return_value=failed):
            assert resolve_repo_root("/not/a/repo") is None


class TestDetectWorktree:
    def test_in_worktree(self, tmp_path, monkeypatch):  # noqa: ARG002
        worktrees_dir = tmp_path / ".worktrees"
        monkeypatch.setattr(reg, "WORKTREES_DIR", worktrees_dir)

        wt_path = worktrees_dir / "myrepo" / "feat-auth"
        wt_path.mkdir(parents=True)

        result = detect_worktree(str(wt_path))
        assert result is not None
        label, path, branch = result
        assert label == "feat-auth"
        assert path == str(wt_path)
        assert branch == "wt/feat-auth"

    def test_not_in_worktree(self, tmp_path, monkeypatch):  # noqa: ARG002
        monkeypatch.setattr(reg, "WORKTREES_DIR", tmp_path / ".worktrees")
        result = detect_worktree(str(tmp_path / "some" / "other" / "dir"))
        assert result is None

    def test_nested_in_worktree(self, tmp_path, monkeypatch):  # noqa: ARG002
        worktrees_dir = tmp_path / ".worktrees"
        monkeypatch.setattr(reg, "WORKTREES_DIR", worktrees_dir)

        nested = worktrees_dir / "myrepo" / "feat" / "src" / "deep"
        nested.mkdir(parents=True)

        result = detect_worktree(str(nested))
        assert result is not None
        label, path, branch = result
        assert label == "feat"
        assert branch == "wt/feat"

    def test_too_shallow(self, tmp_path, monkeypatch):  # noqa: ARG002
        worktrees_dir = tmp_path / ".worktrees"
        monkeypatch.setattr(reg, "WORKTREES_DIR", worktrees_dir)

        # Only one level deep — repo dir without label
        shallow = worktrees_dir / "myrepo"
        shallow.mkdir(parents=True)

        result = detect_worktree(str(shallow))
        assert result is None


class TestRegisterSession:
    def test_new_session(self, db, tmp_path):  # noqa: ARG002
        repo = tmp_path / "myrepo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)

        hook = HookInput(
            session_id="sess-1",
            transcript_path="/path/to/transcript.jsonl",
            cwd=str(repo),
        )
        result = register_session(hook)

        assert result.created is True
        assert result.project.name == "myrepo"
        assert result.project.repo_path == str(repo.resolve())
        assert result.transcript.session_id == "sess-1"
        assert result.worktree is None

    def test_idempotent_re_register(self, db, tmp_path):  # noqa: ARG002
        repo = tmp_path / "myrepo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)

        hook = HookInput(
            session_id="sess-1",
            transcript_path="/path/to/transcript.jsonl",
            cwd=str(repo),
        )
        r1 = register_session(hook)
        r2 = register_session(hook)

        assert r1.created is True
        assert r2.created is False
        assert r1.transcript.id == r2.transcript.id
        # Project should be reused too
        assert r1.project.id == r2.project.id

    def test_reactivates_ended_transcript(self, db, tmp_path):  # noqa: ARG002
        repo = tmp_path / "myrepo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)

        hook = HookInput(
            session_id="sess-ended",
            transcript_path="/path/to/transcript.jsonl",
            cwd=str(repo),
        )
        r1 = register_session(hook)
        assert r1.created is True

        # Simulate transcript being marked ended
        with Database().session() as session:
            t = Transcript.get_by_session_id("sess-ended")
            t.ended_at = datetime.now(UTC)
            t.save(session)

        r2 = register_session(hook)
        assert r2.created is False
        assert r2.transcript.ended_at is None

    def test_with_worktree(self, db, tmp_path, monkeypatch):  # noqa: ARG002
        worktrees_dir = tmp_path / ".worktrees"
        monkeypatch.setattr(reg, "WORKTREES_DIR", worktrees_dir)

        wt_path = worktrees_dir / "myrepo" / "bg-mem"
        wt_path.mkdir(parents=True)
        subprocess.run(["git", "init", str(wt_path)], capture_output=True, check=True)

        hook = HookInput(
            session_id="sess-wt",
            transcript_path="/path/to/transcript.jsonl",
            cwd=str(wt_path),
        )
        result = register_session(hook)

        assert result.worktree is not None
        assert result.worktree.label == "bg-mem"
        assert result.worktree.branch == "wt/bg-mem"
        assert result.transcript.worktree_id == result.worktree.id

    def test_not_a_git_repo(self, db):  # noqa: ARG002
        hook = HookInput(
            session_id="sess-bad",
            transcript_path="/path/to/transcript.jsonl",
            cwd="/not/a/repo",
        )
        with (
            patch("observer.services.registration.resolve_repo_root", return_value=None),
            pytest.raises(RegistrationError, match="Not a git repository"),
        ):
            register_session(hook)

    def test_same_project_different_sessions(self, db, tmp_path):  # noqa: ARG002
        repo = tmp_path / "myrepo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)

        h1 = HookInput(session_id="s1", transcript_path="/t1.jsonl", cwd=str(repo))
        h2 = HookInput(session_id="s2", transcript_path="/t2.jsonl", cwd=str(repo))
        r1 = register_session(h1)
        r2 = register_session(h2)

        assert r1.project.id == r2.project.id
        assert r1.transcript.id != r2.transcript.id
