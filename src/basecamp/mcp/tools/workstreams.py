"""The ``create_workstream`` MCP tool — the recoupled staging call.

One call: mint a slug, create the daemon record, provision the permanent worktree
(``~/.worktrees/<org>/<name>/copilot/<slug>/``), persist its path on the record,
and best-effort open a Herdr pane on it. This is the first ``@mcp.tool`` in the
repo; the git/Herdr/naming primitives live in :mod:`basecamp.claude` so this stays
thin orchestration.

Failure model: the record is created first, then the worktree; a worktree failure
rolls the record back (best-effort delete) so a failed stage leaves nothing
behind. A pane failure is *not* fatal — the record + worktree are valid and the
tool returns a manual next-step. Slug collisions retry against the daemon.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from basecamp.claude import herdr, worktree
from basecamp.claude.identity import repo_identity, repo_root
from basecamp.claude.naming import generate_slug
from basecamp.hub.claude import client

_SLUG_ATTEMPTS = 10


def create_workstream(
    *,
    label: str,
    dossier_path: str | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Stage a workstream: record + permanent worktree + Herdr pane.

    ``label`` is the human title; ``dossier_path`` points at the shared-Logseq work
    page (the brief lives there, not in the record). Returns a result dict with the
    minted ``slug``/``id``, the worktree, and the pane status.
    """

    working_dir = cwd or os.getcwd()
    environ = env if env is not None else dict(os.environ)

    root = repo_root(working_dir)
    if root is None:
        return _error("not a git repository", "Run copilot from inside the repository you are staging work in.")
    repo = repo_identity(working_dir) or Path(root).name

    # 1. Mint a slug the daemon doesn't already have, then create the record.
    workstream_id = f"ws_{uuid.uuid4().hex}"
    outcome = _create_record(workstream_id=workstream_id, label=label, repo=repo, dossier_path=dossier_path)
    if outcome is None:
        return _error("daemon unavailable", "The basecamp daemon could not be reached to record the workstream.")
    slug, created = outcome
    if not created:
        return _error("slug allocation failed", "Could not allocate a unique workstream slug; try again.")

    # 2. Provision the permanent worktree; roll the record back if it fails.
    target = worktree.copilot_worktree_target(label, slug, environ.get("USER", ""))
    try:
        result = worktree.get_or_create_worktree(root, repo, target.label, target.branch)
    except worktree.WorktreeError as exc:
        client.delete_workstream(workstream_id)
        return _error("worktree provisioning failed", str(exc))

    # 3. Persist the worktree path (normalized) so `workstream current` can resolve it.
    normalized = str(Path(result.path).resolve())
    client.set_workstream_worktree(workstream_id, normalized)

    # 4. Best-effort open a Herdr pane; a failure never invalidates the staged workstream.
    pane = herdr.open_pane(
        worktree_path=result.path,
        label=result.label,
        workspace_cwd=root,
        env=environ,
    )

    return {
        "status": "created",
        "id": workstream_id,
        "slug": slug,
        "repo": repo,
        "label": label,
        "dossier_path": dossier_path,
        "worktree": {
            "path": normalized,
            "label": result.label,
            "branch": result.branch,
            "created": result.created,
        },
        "pane": {"status": pane.status, "message": pane.message, "reason": pane.reason},
        "next_step": _next_step(pane, normalized),
    }


def _create_record(
    *,
    workstream_id: str,
    label: str,
    repo: str,
    dossier_path: str | None,
) -> tuple[str, bool] | None:
    """Create the record, retrying on slug collision. ``None`` if the daemon is unreachable."""

    for _ in range(_SLUG_ATTEMPTS):
        slug = generate_slug()
        try:
            result = client.create_workstream(
                workstream_id=workstream_id,
                slug=slug,
                label=label,
                repo=repo,
                dossier_path=dossier_path,
            )
        except client.DaemonError:
            return None
        if result.created:
            return slug, True
        if not result.slug_conflict:
            return slug, False
    return "", False


def _next_step(pane: herdr.HerdrResult, worktree_path: str) -> str:
    if pane.status == "opened":
        return "Open the new Herdr pane and start Claude there, then run /basecamp:start-workstream."
    return f"cd '{worktree_path}' && claude, then run /basecamp:start-workstream."


def _error(status: str, message: str) -> dict[str, Any]:
    return {"status": "failed", "error": status, "message": message}
