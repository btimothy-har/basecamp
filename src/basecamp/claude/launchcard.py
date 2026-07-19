"""The ``bcc`` launch context card.

A terminal display printed just before the launcher hands off to ``claude`` (see
:mod:`basecamp.claude.launch`). It surfaces *for the user* what basecamp wired up
for the session — the same project awareness the MCP server injects for the model:
repo identity, the related-directory working set, standing context, and durable
Logseq memory.

The card renders with ``rich`` (the codebase's terminal-output convention) so the
box, colour, and TTY detection come for free. It is **strictly fail-open**: any
error gathering or rendering the card yields no output, never a failed launch.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.text import Text

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


def render_launch_card(card: LaunchCard) -> RenderableType:
    """Render a :class:`LaunchCard` into a ``rich`` renderable."""
    panel = Panel(
        Text(_identity_line(card)),
        title="basecamp",
        title_align="left",
        border_style="cyan",
        expand=False,
    )

    lines: list[RenderableType] = []
    if card.protected_checkout:
        lines.append(Text.assemble(("Checkout: ", "bold"), (str(card.active_worktree), "")))
        lines.append(Text(f"          protected: {card.protected_checkout}", style="dim"))

    if card.projected:
        lines.append(_related_dirs_block(card))
        if card.context_loaded:
            lines.append(Text.assemble(("Context: ", "bold"), ("✓ standing context loaded", "green")))
    elif card.is_repo:
        lines.append(Text("No basecamp project configured for this directory.", style="dim"))
    # A non-repo directory is a valid session (general/scratch work); it shows the
    # minimal identity + scratch card, with no git-repo notice — nothing failed.

    if card.is_repo:
        lines.append(_memory_line(card))

    lines.append(Text.assemble(("Scratch: ", "bold"), (card.scratch_dir, "dim")))
    lines += [Text(f"⚠ {warning}", style="yellow") for warning in card.warnings]

    return Group(panel, *lines)


def print_launch_card(
    cwd: str,
    *,
    scratch_dir: str | Path,
    home: Path | None = None,
    console: Console | None = None,
) -> None:
    """Gather, render, and print the launch card. Never raises."""
    try:
        card = gather_launch_card(cwd, scratch_dir=scratch_dir, home=home)
        if card is None:
            return
        (console or Console()).print(render_launch_card(card))
    except Exception:  # noqa: BLE001  # fail-open: printing a card must never break launch
        return


def _identity_line(card: LaunchCard) -> str:
    parts = [card.display_name or "session"]
    if card.branch:
        parts.append(card.branch)
    if card.active_worktree:
        parts.append("worktree")
    return " · ".join(parts)


def _related_dirs_block(card: LaunchCard) -> RenderableType:
    if not card.related_dirs:
        return Text("Related dirs: none configured", style="dim")
    header = Text("Related dirs:", style="bold")
    return Group(header, *(Text(f"  {directory}", style="dim") for directory in card.related_dirs))


def _memory_line(card: LaunchCard) -> RenderableType:
    if not card.logseq_available:
        reason = card.logseq_reason or "durable repo memory unavailable"
        return Text.assemble(("Memory: ", "bold"), (f"unavailable — {reason}", "dim"))
    cockpit = "✓" if card.cockpit_present else "seed pending"
    count = card.dossier_count
    dossiers = f"{count} dossier{'' if count == 1 else 's'}"
    detail = f"{card.cockpit_name} ({cockpit}) · {dossiers}"
    return Text.assemble(("Memory: ", "bold"), (detail, ""))
