"""Tests for basecamp.claude.naming — three-word slug generation."""

from __future__ import annotations

import re

import pytest

from basecamp.claude.naming import generate_slug


def test_generate_slug_shape() -> None:
    slug = generate_slug()
    assert re.fullmatch(r"[a-z]+-[a-z]+-[a-z]+", slug), slug


def test_generate_slug_retries_past_taken() -> None:
    seen: set[str] = set()
    calls: list[str] = []

    def is_taken(candidate: str) -> bool:
        calls.append(candidate)
        # reject the first two distinct candidates, accept the third
        if len(seen) < 2 and candidate not in seen:
            seen.add(candidate)
            return True
        return False

    slug = generate_slug(is_taken)
    assert slug not in seen
    assert len(calls) >= 3


def test_generate_slug_raises_when_all_taken() -> None:
    with pytest.raises(RuntimeError, match="unique workstream slug"):
        generate_slug(lambda _c: True)
