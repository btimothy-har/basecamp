"""The ``bcc`` launch context card.

Surfaces *for the user* what basecamp wired up for the session — the same project
awareness the MCP server injects for the model: repo identity, the related-directory
working set, standing context, and durable Logseq memory.

The card is rendered as plain text and delivered by the ``SessionStart`` hook as a
``systemMessage`` (see :func:`basecamp.hooks.session.handle_session_start`), so it
lands *inside* the session where the user can read it — Claude Code's alternate-screen
TUI wipes anything the launcher prints before handing off. Claude wraps a
``systemMessage`` under a fixed, single-style prefix, so the text carries no box or
colour of its own. Gathering is **strictly fail-open**: any error yields ``None``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from basecamp.claude.gitutil import main_worktree, run_git
from basecamp.claude.identity import repo_identity, repo_root
from basecamp.claude.logseq import resolve_logseq
from basecamp.mcp.resolve import resolve_project


@dataclass(frozen=True)
class LaunchCard:
    """Structured launch facts, gathered from the local fail-open resolvers."""

    scratch_dir: str
    is_repo: bool = False
    projected: bool = False
    display_name: str | None = None
    branch: str | None = None
    active_worktree: str | None = None
    protected_checkout: str | None = None
    related_dirs: tuple[str, ...] = ()
    context_loaded: bool = False
    cockpit_name: str | None = None
    cockpit_present: bool = False
    dossier_count: int = 0
    logseq_available: bool = False
    logseq_reason: str | None = None
    warnings: tuple[str, ...] = ()


def gather_launch_card(cwd: str, *, scratch_dir: str | Path, home: Path | None = None) -> LaunchCard | None:
    """Assemble a :class:`LaunchCard` for ``cwd``, or ``None`` on any failure."""
    try:
        return _build_card(cwd, str(scratch_dir), home)
    except Exception:  # noqa: BLE001  # fail-open: a card must never break launch
        return None


def _build_card(cwd: str, scratch_dir: str, home: Path | None) -> LaunchCard:
    root = repo_root(cwd)
    is_repo = root is not None
    identity = repo_identity(cwd) if is_repo else None
    display_name = identity or (os.path.basename(os.path.abspath(cwd)) or "session")
    branch = run_git(cwd, "rev-parse", "--abbrev-ref", "HEAD") if is_repo else None

    active_worktree, protected_checkout = _worktree_pair(cwd, root)

    project = resolve_project(cwd, home=home) if is_repo else None
    logseq = resolve_logseq(cwd, home=home) if is_repo else None

    projected = bool(project and project.projected)
    context_loaded = bool(project and project.context_text is not None)
    warnings = list(project.warnings) if project else []
    if projected and not context_loaded:
        warnings.append("standing context not configured")

    return LaunchCard(
        scratch_dir=scratch_dir,
        is_repo=is_repo,
        projected=projected,
        display_name=display_name,
        branch=branch,
        active_worktree=active_worktree,
        protected_checkout=protected_checkout,
        related_dirs=tuple(project.related_dirs) if project else (),
        context_loaded=context_loaded,
        cockpit_name=logseq.cockpit_name if logseq else None,
        cockpit_present=bool(logseq and logseq.cockpit_text is not None),
        dossier_count=len(logseq.dossier_paths) if logseq else 0,
        logseq_available=bool(logseq and logseq.available),
        logseq_reason=logseq.reason if logseq else None,
        warnings=tuple(warnings),
    )


def _worktree_pair(cwd: str, root: str | None) -> tuple[str | None, str | None]:
    if root is None:
        return None, None
    main = main_worktree(cwd)
    if main and os.path.realpath(main) != os.path.realpath(root):
        return root, main
    return None, None


def render_launch_card_text(card: LaunchCard) -> str:
    """Render a :class:`LaunchCard` as plain text for the SessionStart ``systemMessage``."""
    lines: list[str] = [f"basecamp · {_identity_line(card)}"]

    if card.protected_checkout:
        lines.append(f"checkout: {card.active_worktree}")
        lines.append(f"protected: {card.protected_checkout}")

    if card.projected:
        lines.extend(_related_dirs_lines(card))
        if card.context_loaded:
            lines.append("context: standing context loaded")
    elif card.is_repo:
        lines.append("no basecamp project configured for this directory")
    # A non-repo directory is a valid session (general/scratch work): minimal identity
    # + scratch, with no git-repo notice — nothing failed.

    if card.is_repo:
        lines.append(_memory_line(card))

    lines.append(f"scratch: {card.scratch_dir}")
    lines.extend(f"⚠ {warning}" for warning in card.warnings)

    return "\n".join(lines)


def _identity_line(card: LaunchCard) -> str:
    parts = [card.display_name or "session"]
    if card.branch:
        parts.append(card.branch)
    if card.active_worktree:
        parts.append("worktree")
    return " · ".join(parts)


def _related_dirs_lines(card: LaunchCard) -> list[str]:
    if not card.related_dirs:
        return ["related dirs: none configured"]
    return ["related dirs:", *(f"  {directory}" for directory in card.related_dirs)]


def _memory_line(card: LaunchCard) -> str:
    if not card.logseq_available:
        reason = card.logseq_reason or "durable repo memory unavailable"
        return f"memory: unavailable — {reason}"
    cockpit = "✓" if card.cockpit_present else "seed pending"
    count = card.dossier_count
    dossiers = f"{count} dossier{'' if count == 1 else 's'}"
    return f"memory: {card.cockpit_name} ({cockpit}) · {dossiers}"
