"""The ``basecamp workstream`` command group.

Two ways to pick up a staged workstream, both printing pointers (not content —
the daemon never stores the brief; the dossier file does):

- ``current`` infers the workstream from the worktree you are in (the pane
  copilot opened) — zero-arg convenience via the daemon's ``by-worktree`` route.
- ``show <slug>`` resolves a named workstream from anywhere via id/slug, so a
  workstream can be started from a different repo (cross-repo carry).

Both print ``repo`` and ``worktree`` so the ``start-workstream`` skill can decide
where to execute: in the workstream's home repo it is anchored to its provisioned
worktree; in a different repo the brief is portable and executed in place.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import rich_click as click

from basecamp.hub.claude import client

_GIT_TIMEOUT_S = 5


@click.group()
def workstream() -> None:
    """Workstream handoff commands."""


@workstream.command()
def current() -> None:
    """Print the workstream owning the current worktree (infers from cwd)."""
    worktree_path = _current_worktree_path()
    if worktree_path is None:
        _fail("not inside a git worktree")
    record = client.get_workstream_by_worktree(worktree_path)
    if record is None:
        _fail("no workstream is registered for this worktree (is the daemon running?)")
    _print_record(record)


@workstream.command()
@click.argument("identifier")
def show(identifier: str) -> None:
    """Print a workstream by slug or id (works from any repo or directory)."""
    record = client.get_workstream(identifier)
    if record is None:
        _fail(f"no workstream found for {identifier!r} (is the daemon running?)")
    _print_record(record)


def _print_record(record: dict[str, Any]) -> None:
    label = record.get("label") or record.get("slug") or "(unnamed)"
    click.echo(f"label: {label}")
    click.echo(f"slug: {record.get('slug', '')}")
    click.echo(f"status: {record.get('status', '')}")
    click.echo(f"repo: {record.get('repo', '')}")
    # `worktree` is the home worktree copilot provisioned; `dossier` is the brief
    # page. Both are pointers the skill acts on (the brief itself is in the file).
    click.echo(f"worktree: {record.get('worktree_path', '') or ''}")
    click.echo(f"dossier: {record.get('dossier_path', '') or ''}")


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
