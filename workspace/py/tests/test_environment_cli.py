"""Tests for basecamp-workspace environment CLI helpers."""

from __future__ import annotations

import pytest
from basecamp.workspace.cli.environment import derive_repo_identity


@pytest.mark.parametrize(
    ("remote_url", "expected"),
    [
        ("git@github.com:org/name.git", "org/name"),
        ("ssh://git@github.com/org/name.git", "org/name"),
        ("https://github.com/org/name", "org/name"),
        ("https://github.com/org/name.git", "org/name"),
        ("https://github.com/org/name.git/", "org/name"),
        ("git@gitlab.com:group/sub.git", "group/sub"),
        ("../repo.git", "fallback"),
        ("/local/path/repo.git", "fallback"),
        (None, "fallback"),
        ("", "fallback"),
        ("   ", "fallback"),
        ("not-a-url", "fallback"),
    ],
)
def test_derive_repo_identity(remote_url: str | None, expected: str) -> None:
    assert derive_repo_identity(remote_url, "fallback") == expected
