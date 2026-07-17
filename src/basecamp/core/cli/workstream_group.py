"""The ``basecamp workstream`` command group.

``basecamp workstream current`` resolves which workstream owns the current
worktree and prints its brief label + dossier **path** (pointers, not content —
the daemon never stores the brief; the dossier file does). The ``start-workstream``
skill inlines this call, then Reads the printed dossier path itself.

Hub-authoritative lookup: the cwd's worktree top-level is normalized the same way
``create_workstream`` persisted it (absolute, symlink-free) and matched against
the daemon's ``by-worktree`` route. Read-only — it records nothing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import rich_click as click

from basecamp.hub.claude import client

_GIT_TIMEOUT_S = 5


@click.group()
def workstream() -> None:
    """Workstream handoff commands."""


@workstream.command()
def current() -> None:
    """Print the workstream owning the current worktree (brief label + dossier path)."""
    worktree_path = _current_worktree_path()
    if worktree_path is None:
        _fail("not inside a git worktree")

    record = client.get_workstream_by_worktree(worktree_path)
    if record is None:
        _fail("no workstream is registered for this worktree (is the daemon running?)")

    label = record.get("label") or record.get("slug") or "(unnamed)"
    dossier = record.get("dossier_path") or ""
    click.echo(f"label: {label}")
    click.echo(f"slug: {record.get('slug', '')}")
    # A machine-friendly line the skill greps/Reads. Empty when no dossier is linked.
    click.echo(f"dossier: {dossier}")


def _current_worktree_path() -> str | None:
    """Normalized top-level of the git worktree containing the cwd (absolute, symlink-free)."""
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
