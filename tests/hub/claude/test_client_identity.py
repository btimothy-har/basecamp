"""Tests for register-frame identity derivation (env + git-origin fallback)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from basecamp.hub.claude.client.identity import _parse_repo_identity, build_register_frame, resolve_node_id


def test_env_driven_worker_populates_all_facets() -> None:
    env = {
        "BASECAMP_AGENT_ID": "handle-node",
        "BASECAMP_USER_FACING": "0",
        "BASECAMP_REPO": "acme/widgets",
        "BASECAMP_WORKTREE_LABEL": "copilot/brave-otter-quill",
        "BASECAMP_AGENT_DEPTH": "2",
        "BASECAMP_PARENT_SESSION": "parent-1",
        "BASECAMP_SIBLING_GROUP": "sg-1",
        "BASECAMP_SESSION_NAME": "custom-name",
    }

    frame = build_register_frame(
        session_id="sess-abc",
        cwd="/work/dir",
        transcript_path="/transcripts/sess-abc.jsonl",
        env=env,
    )

    assert frame.node_id == "handle-node"
    assert frame.role == "worker"
    assert frame.repo == "acme/widgets"
    assert frame.worktree_label == "copilot/brave-otter-quill"
    assert frame.depth == 2
    assert frame.parent_id == "parent-1"
    assert frame.sibling_group == "sg-1"
    assert frame.session_name == "custom-name"
    assert frame.session_file == "/transcripts/sess-abc.jsonl"
    assert frame.type == "register"
    assert frame.agent_handle is None


def test_plain_session_defaults_to_session_id_and_agent_role(tmp_path: Path) -> None:
    frame = build_register_frame(
        session_id="sess-xyz",
        cwd=str(tmp_path),  # not a git repo → no repo derivation
        transcript_path=None,
        env={},
    )

    assert frame.node_id == "sess-xyz"
    assert frame.role == "agent"
    assert frame.repo is None
    assert frame.depth == 0
    assert frame.parent_id is None
    assert frame.sibling_group is None
    assert frame.session_name == tmp_path.name
    assert frame.session_file is None


def test_session_name_falls_back_to_repo_when_unnamed() -> None:
    frame = build_register_frame(
        session_id="sess-1",
        cwd="/work/dir",
        transcript_path=None,
        env={"BASECAMP_REPO": "acme/widgets"},
    )

    assert frame.session_name == "acme/widgets"


@pytest.mark.parametrize(
    ("depth_raw", "expected"),
    [("abc", 0), ("-1", 0), ("3", 3), ("0", 0)],
)
def test_depth_is_sanitized(depth_raw: str, expected: int) -> None:
    frame = build_register_frame(
        session_id="sess-1",
        cwd="/work/dir",
        transcript_path=None,
        env={"BASECAMP_AGENT_DEPTH": depth_raw, "BASECAMP_REPO": "a/b"},
    )
    assert frame.depth == expected


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
    ],
)
def test_parse_repo_identity(url: str, expected: str | None) -> None:
    assert _parse_repo_identity(url) == expected


def test_resolve_node_id_prefers_agent_id() -> None:
    assert resolve_node_id("sess-1", {"BASECAMP_AGENT_ID": "node-9"}) == "node-9"


def test_resolve_node_id_falls_back_to_session_id() -> None:
    assert resolve_node_id("sess-1", {}) == "sess-1"
    assert resolve_node_id("sess-1", {"BASECAMP_AGENT_ID": "   "}) == "sess-1"


def test_repo_derived_from_git_origin(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:acme/widgets.git"],
        cwd=tmp_path,
        check=True,
    )

    frame = build_register_frame(
        session_id="sess-1",
        cwd=str(tmp_path),
        transcript_path=None,
        env={},
    )

    assert frame.repo == "acme/widgets"
    assert frame.session_name == "acme/widgets"
