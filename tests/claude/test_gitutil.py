"""Tests for basecamp.claude.gitutil — the shared git runner + remote parser."""

from __future__ import annotations

import subprocess
from pathlib import Path

from basecamp.claude.gitutil import parse_remote_identity, run_git


def test_parse_https_remote() -> None:
    assert parse_remote_identity("https://github.com/acme/web-app.git") == "acme/web-app"


def test_parse_ssh_scp_remote() -> None:
    assert parse_remote_identity("git@github.com:acme/web-app.git") == "acme/web-app"


def test_parse_ssh_scheme_remote() -> None:
    assert parse_remote_identity("ssh://git@github.com/acme/web-app.git") == "acme/web-app"


def test_parse_nested_takes_last_two() -> None:
    assert parse_remote_identity("https://gitlab.com/group/sub/proj.git") == "sub/proj"


def test_parse_filesystem_origin_is_none() -> None:
    # a bare path origin is not a recognized remote form
    assert parse_remote_identity("/srv/git/repo.git") is None


def test_parse_single_segment_is_none() -> None:
    assert parse_remote_identity("https://example.com/onlyone") is None


def test_run_git_success_and_failure(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    # a successful command returns stripped stdout
    assert run_git(str(repo), "rev-parse", "--show-toplevel") == str(repo.resolve())
    # a failing command (not a repo) returns None, not a raised error
    assert run_git(str(tmp_path / "not-a-repo"), "rev-parse", "--show-toplevel") is None
