"""Tests for register-body identity derivation (env + git-origin fallback)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from basecamp.hub.claude.client.identity import _parse_repo_identity, build_register_body


def test_body_carries_native_session_id_and_env_facets() -> None:
    env = {
        "BASECAMP_REPO": "acme/widgets",
        "BASECAMP_WORKTREE_LABEL": "copilot/brave-otter-quill",
    }

    body = build_register_body(
        session_id="sess-abc",
        cwd="/work/dir",
        transcript_path="/transcripts/sess-abc.jsonl",
        source="startup",
        env=env,
    )

    assert body.session_id == "sess-abc"
    assert body.cwd == "/work/dir"
    assert body.transcript_path == "/transcripts/sess-abc.jsonl"
    assert body.repo == "acme/widgets"
    assert body.worktree_label == "copilot/brave-otter-quill"
    assert body.source == "startup"
    assert body.handle is None


def test_plain_session_has_no_repo_or_worktree(tmp_path: Path) -> None:
    body = build_register_body(
        session_id="sess-xyz",
        cwd=str(tmp_path),  # not a git repo → no repo derivation
        transcript_path=None,
        env={},
    )

    assert body.session_id == "sess-xyz"
    assert body.repo is None
    assert body.worktree_label is None
    assert body.transcript_path is None
    assert body.source is None


def test_blank_transcript_path_normalizes_to_none() -> None:
    body = build_register_body(
        session_id="sess-1",
        cwd="/work/dir",
        transcript_path="",
        env={"BASECAMP_REPO": "acme/widgets"},
    )

    assert body.transcript_path is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/acme/widgets.git", "acme/widgets"),
        ("git@github.com:acme/widgets.git", "acme/widgets"),
        ("ssh://git@host.example/acme/widgets", "acme/widgets"),
        ("https://host/org/sub/widgets.git", "sub/widgets"),
        ("widgets", None),
        ("", None),
        # Filesystem-path origins are not remote URLs: return None so the caller
        # falls through to the toplevel basename, matching derive_repo_identity.
        ("/home/user/org/repo", None),
        ("file:///srv/git/org/repo.git", None),
        # Traversal segments are dropped so a crafted/mistyped origin never
        # registers a "../…" repo identity in the daemon store.
        ("https://host/../.ssh", None),
        ("https://host/../..", None),
        ("https://host/org/../name", "org/name"),
    ],
)
def test_parse_repo_identity(url: str, expected: str | None) -> None:
    assert _parse_repo_identity(url) == expected


def test_repo_derived_from_git_origin(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:acme/widgets.git"],
        cwd=tmp_path,
        check=True,
    )

    body = build_register_body(
        session_id="sess-1",
        cwd=str(tmp_path),
        transcript_path=None,
        env={},
    )

    assert body.repo == "acme/widgets"
