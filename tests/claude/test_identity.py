"""Tests for basecamp.claude.identity — canonical <org>/<name> derivation."""

from __future__ import annotations

import subprocess
from pathlib import Path

from basecamp.claude.identity import _parse_remote_identity, repo_identity


def _init_repo(path: Path, origin: str | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    if origin is not None:
        subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True)


def test_parse_https_remote() -> None:
    assert _parse_remote_identity("https://github.com/acme/web-app.git") == "acme/web-app"


def test_parse_ssh_scp_remote() -> None:
    assert _parse_remote_identity("git@github.com:acme/web-app.git") == "acme/web-app"


def test_parse_nested_takes_last_two() -> None:
    assert _parse_remote_identity("https://gitlab.com/group/sub/proj.git") == "sub/proj"


def test_parse_filesystem_origin_is_none() -> None:
    # a bare path origin is not a recognized remote form
    assert _parse_remote_identity("/srv/git/repo.git") is None


def test_repo_identity_from_origin(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, "https://github.com/acme/web-app.git")
    assert repo_identity(str(repo)) == "acme/web-app"


def test_repo_identity_falls_back_to_basename(tmp_path: Path) -> None:
    repo = tmp_path / "lonely-repo"
    _init_repo(repo)  # no origin
    assert repo_identity(str(repo)) == "lonely-repo"


def test_repo_identity_none_outside_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert repo_identity(str(plain)) is None
