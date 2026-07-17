"""The ``basecamp workstream`` command group.

Pick up and attach to a workstream. All reads print pointers, not content — the
daemon never stores the brief; the dossier file does.

- ``current`` derives the workstream from the worktree you are in — its path ends
  in ``copilot/<slug>``, so the slug is read from the path and looked up by slug.
  No daemon worktree-index needed; robust to whatever branch the worktree is on.
- ``show <slug>`` resolves a named workstream from anywhere via id/slug, so a
  workstream can be started from a different repo (cross-repo carry).
- ``attach <slug>`` links this session (agent) to the workstream, carrying this
  agent's own repo + worktree. Many agents attach to one workstream — this is what
  makes it multi-worker and portable; the record holds no single worktree.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import rich_click as click

from basecamp.claude.identity import repo_identity
from basecamp.hub.claude import client

_GIT_TIMEOUT_S = 5


@click.group()
def workstream() -> None:
    """Workstream handoff commands."""


@workstream.command()
def current() -> None:
    """Print the workstream for the current worktree (derives the slug from its path)."""
    slug = _slug_from_worktree()
    if slug is None:
        _fail("not inside a workstream worktree (expected a path under copilot/<slug>)")
    record = client.get_workstream(slug)
    if record is None:
        _fail(f"no workstream found for {slug!r} (is the daemon running?)")
    _print_record(record)


@workstream.command()
@click.argument("identifier")
def show(identifier: str) -> None:
    """Print a workstream by slug or id (works from any repo or directory)."""
    record = client.get_workstream(identifier)
    if record is None:
        _fail(f"no workstream found for {identifier!r} (is the daemon running?)")
    _print_record(record)


@workstream.command()
@click.argument("identifier")
def attach(identifier: str) -> None:
    """Attach this session (agent) to a workstream, carrying this repo + worktree.

    Reads the native ``CLAUDE_CODE_SESSION_ID``; run from the worktree the agent
    is working in. Many agents can attach to one workstream (multi-worker), each
    from its own repo — this is what makes a workstream portable.
    """
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if not session_id:
        _fail("no CLAUDE_CODE_SESSION_ID in the environment; run this inside a Claude session")
    cwd = os.getcwd()
    ok = client.attach_workstream_session(
        identifier,
        session_id,
        repo=repo_identity(cwd),
        worktree_path=_worktree_toplevel(),
    )
    if not ok:
        _fail(f"could not attach to {identifier!r} (unknown workstream, or the daemon is down)")
    click.echo(f"attached to {identifier}")


def _print_record(record: dict[str, Any]) -> None:
    label = record.get("label") or record.get("slug") or "(unnamed)"
    click.echo(f"label: {label}")
    click.echo(f"slug: {record.get('slug', '')}")
    click.echo(f"live: {'yes' if record.get('live') else 'no'}")
    click.echo(f"repo: {record.get('repo', '')}")
    # `dossier` is the external Logseq work page (the brief); the skill Reads it.
    click.echo(f"dossier: {record.get('dossier_path', '') or ''}")


def _slug_from_worktree() -> str | None:
    """Extract ``<slug>`` from a ``copilot/<slug>`` worktree path, or ``None``.

    The worktree top-level ends in ``copilot/<slug>``; the slug lives in the path
    itself, so a fresh session in that worktree resolves its workstream without any
    daemon worktree-index — and it survives the session creating other branches.
    """
    top = _worktree_toplevel()
    if top is None:
        return None
    parts = Path(top).parts
    for i in range(len(parts) - 1):
        if parts[i] == "copilot":
            return parts[i + 1]
    return None


def _worktree_toplevel() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    top = result.stdout.strip()
    return str(Path(top).resolve()) if top else None


def _fail(message: str) -> None:
    raise click.ClickException(message)
