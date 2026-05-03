"""Tests for the registration service."""

import subprocess
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from observer.data.transcript import Transcript
from observer.exceptions import RegistrationError
from observer.services.db import Database
from observer.services.registration import (
    HookInput,
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

    def test_explicit_repo_metadata_does_not_require_git_inference(self, db, tmp_path):  # noqa: ARG002
        repo = tmp_path / "explicit-repo"

        hook = HookInput(
            session_id="sess-explicit-repo",
            transcript_path="/path/to/transcript.jsonl",
            cwd="/not/a/repo",
            repo_name="  explicit-name  ",
            repo_root=str(repo),
        )
        with patch("observer.services.registration.resolve_repo_root", return_value=None) as mock_resolve:
            result = register_session(hook)

        mock_resolve.assert_not_called()
        assert result.created is True
        assert result.project.name == "explicit-name"
        assert result.project.repo_path == str(repo.resolve())
        assert result.worktree is None

    def test_missing_repo_root_falls_back_to_resolve_repo_root(self, db, tmp_path):  # noqa: ARG002
        repo = tmp_path / "fallback-repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)

        hook = HookInput(
            session_id="sess-fallback",
            transcript_path="/path/to/transcript.jsonl",
            cwd=str(repo),
        )
        result = register_session(hook)

        assert result.created is True
        assert result.project.name == "fallback-repo"
        assert result.project.repo_path == str(repo.resolve())
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

    def test_explicit_execution_target_creates_worktree(self, db, tmp_path):  # noqa: ARG002
        repo = tmp_path / "myrepo"
        wt_path = tmp_path / ".worktrees" / "myrepo" / "bg-mem"
        wt_path.mkdir(parents=True)

        hook = HookInput(
            session_id="sess-wt",
            transcript_path="/path/to/transcript.jsonl",
            cwd=str(wt_path),
            repo_root=str(repo),
            execution_target={
                "kind": "git-worktree",
                "label": "bg-mem",
                "path": str(wt_path),
                "branch": "bh/bg-mem",
            },
        )
        result = register_session(hook)

        assert result.worktree is not None
        assert result.worktree.label == "bg-mem"
        assert result.worktree.path == str(wt_path)
        assert result.worktree.branch == "bh/bg-mem"
        assert result.transcript.worktree_id == result.worktree.id

    def test_cwd_under_worktrees_without_execution_target_does_not_create_worktree(self, db, tmp_path):  # noqa: ARG002
        wt_path = tmp_path / ".worktrees" / "myrepo" / "bg-mem"
        wt_path.mkdir(parents=True)
        subprocess.run(["git", "init", str(wt_path)], capture_output=True, check=True)

        hook = HookInput(
            session_id="sess-no-explicit-wt",
            transcript_path="/path/to/transcript.jsonl",
            cwd=str(wt_path),
        )
        result = register_session(hook)

        assert result.created is True
        assert result.worktree is None
        assert result.transcript.worktree_id is None

    def test_malformed_execution_target_does_not_create_worktree(self, db, tmp_path):  # noqa: ARG002
        repo = tmp_path / "myrepo"
        wt_path = tmp_path / ".worktrees" / "myrepo" / "bg-mem"
        wt_path.mkdir(parents=True)

        hook = HookInput(
            session_id="sess-bad-wt",
            transcript_path="/path/to/transcript.jsonl",
            cwd=str(wt_path),
            repo_root=str(repo),
            execution_target={
                "kind": "git-worktree",
                "label": "bg-mem",
                "branch": "bh/bg-mem",
            },
        )
        result = register_session(hook)

        assert result.created is True
        assert result.worktree is None
        assert result.transcript.worktree_id is None

    def test_execution_target_without_branch_defaults_to_detached(self, db, tmp_path):  # noqa: ARG002
        repo = tmp_path / "myrepo"
        wt_path = tmp_path / ".worktrees" / "myrepo" / "detached-work"
        wt_path.mkdir(parents=True)

        hook = HookInput(
            session_id="sess-detached-wt",
            transcript_path="/path/to/transcript.jsonl",
            cwd=str(wt_path),
            repo_root=str(repo),
            execution_target={
                "kind": "git-worktree",
                "label": "detached-work",
                "path": str(wt_path),
                "branch": "",
            },
        )
        result = register_session(hook)

        assert result.worktree is not None
        assert result.worktree.branch == "detached"
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
