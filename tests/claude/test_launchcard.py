"""Tests for basecamp.claude.launchcard — the ``bcc`` launch context card.

Rendering is tested against hand-built ``LaunchCard`` objects (pure, hermetic);
gathering is tested against throwaway git repos and asserted only on structural
facts (never on this machine's real project/Logseq config); fail-open behaviour
is tested by forcing a resolver to raise.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from basecamp.claude import launchcard
from basecamp.claude.launchcard import (
    LaunchCard,
    gather_launch_card,
    render_launch_card_text,
)


def _render(card: LaunchCard) -> str:
    return render_launch_card_text(card)


def _init_repo(path: Path, origin: str | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    if origin is not None:
        subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-q", "-m", "init"],
        cwd=path,
        check=True,
    )


def test_render_projected_card_shows_full_context() -> None:
    card = LaunchCard(
        scratch_dir="/tmp/claude/acme/web",
        is_repo=True,
        projected=True,
        display_name="acme/web",
        branch="main",
        related_dirs=("/src/acme/shared", "/src/acme/proto"),
        context_loaded=True,
        cockpit_name="repo__acme__web",
        cockpit_present=True,
        dossier_count=3,
        logseq_available=True,
    )

    out = _render(card)

    assert "basecamp" in out
    assert "acme/web" in out and "main" in out
    assert "related dirs:" in out
    assert "/src/acme/shared" in out and "/src/acme/proto" in out
    assert "context: standing context loaded" in out
    assert "repo__acme__web" in out and "3 dossiers" in out
    assert "/tmp/claude/acme/web" in out


def test_render_missing_context_surfaces_warning() -> None:
    card = LaunchCard(
        scratch_dir="/tmp/claude/acme/web",
        is_repo=True,
        projected=True,
        display_name="acme/web",
        branch="main",
        logseq_available=True,
        cockpit_name="repo__acme__web",
        warnings=("standing context not configured",),
    )

    out = _render(card)

    assert "⚠ standing context not configured" in out
    assert "context: standing context loaded" not in out


def test_render_unprojected_repo() -> None:
    card = LaunchCard(scratch_dir="/tmp/claude/x", is_repo=True, display_name="x", branch="main")

    out = _render(card)

    assert "no basecamp project configured for this directory" in out
    assert "related dirs:" not in out


def test_render_non_repo_is_minimal() -> None:
    card = LaunchCard(scratch_dir="/tmp/claude/session", display_name="tmp")

    out = _render(card)

    assert "tmp" in out  # identity still shown
    assert "/tmp/claude/session" in out  # scratch still shown
    assert "no basecamp project configured" not in out  # a non-repo session is valid, not an error
    assert "memory:" not in out
    assert "⚠" not in out


def test_render_worktree_reports_protected_checkout() -> None:
    card = LaunchCard(
        scratch_dir="/tmp/claude/acme/web",
        is_repo=True,
        display_name="acme/web",
        branch="feat-x",
        active_worktree="/wt/feat-x",
        protected_checkout="/repo",
    )

    out = _render(card)

    assert "worktree" in out
    assert "/wt/feat-x" in out
    assert "protected: /repo" in out


def test_render_logseq_unavailable_shows_reason() -> None:
    card = LaunchCard(
        scratch_dir="/tmp/claude/acme/web",
        is_repo=True,
        projected=True,
        display_name="acme/web",
        logseq_available=False,
        logseq_reason="graph not configured",
    )

    out = _render(card)

    assert "memory: unavailable — graph not configured" in out


def test_gather_in_repo_reports_identity_and_branch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, "https://github.com/acme/web.git")

    card = gather_launch_card(str(repo), scratch_dir="/tmp/claude/acme/web", home=tmp_path)

    assert card is not None
    assert card.is_repo is True
    assert card.display_name == "acme/web"
    assert card.branch is not None
    assert card.scratch_dir == "/tmp/claude/acme/web"


def test_gather_outside_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    card = gather_launch_card(str(plain), scratch_dir="/tmp/claude/plain", home=tmp_path)

    assert card is not None
    assert card.is_repo is False
    assert card.projected is False
    assert card.display_name == "plain"


def test_gather_is_fail_open(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(launchcard, "resolve_project", _boom)

    assert gather_launch_card(str(repo), scratch_dir="/tmp/x", home=tmp_path) is None
