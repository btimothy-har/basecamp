"""Tests for basecamp.claude.identity — canonical <org>/<name> derivation.

The remote-URL parser itself lives in and is tested via basecamp.claude.gitutil;
these cover the git-backed repo_identity/repo_root wrappers.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from basecamp.claude.identity import repo_identity, repo_root


def _init_repo(path: Path, origin: str | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    if origin is not None:
        subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True)


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


def test_repo_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    assert repo_root(str(repo)) == str(repo.resolve())
    assert repo_root(str(tmp_path / "plain-nonrepo")) is None
