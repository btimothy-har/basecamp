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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

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
    record = _create_record(workstream_id=workstream_id, label=label, repo=repo, dossier_path=dossier_path)
    if record.error is not None:
        return _error(record.error, record.message)
    slug = record.slug

    # 2. Provision a default worktree; roll the record back if it fails. Agents attach
    #    their own repo/worktree at start, so the record stores no worktree path — this
    #    is just the convenient first home for "shape it, start it now". The branch is
    #    derived from the unique slug (not the human label) so two similarly-titled
    #    workstreams never collide on an already-checked-out branch.
    target = worktree.copilot_worktree_target(slug, slug, environ.get("USER", ""))
    try:
        result = worktree.get_or_create_worktree(root, repo, target.label, target.branch)
    except worktree.WorktreeError as exc:
        if not client.delete_workstream(workstream_id):
            # The stage failed but the record could not be rolled back — surface it so
            # the caller knows an orphan (slug-consuming) record was left behind.
            return _error(
                "worktree provisioning failed",
                f"{exc} (the workstream record {slug} could not be rolled back and may need manual cleanup)",
            )
        return _error("worktree provisioning failed", str(exc))
    normalized = str(Path(result.path).resolve())

    # 3. Best-effort open a Herdr pane; a failure never invalidates the staged workstream.
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


@dataclass(frozen=True)
class _RecordResult:
    """Outcome of minting the workstream record: a slug on success, else an error."""

    slug: str = ""
    error: str | None = None
    message: str = ""


def _create_record(
    *,
    workstream_id: str,
    label: str,
    repo: str,
    dossier_path: str | None,
) -> _RecordResult:
    """Create the record, retrying on slug collision.

    Distinguishes the failure modes rather than collapsing them: a transport/daemon
    error (``ensure_daemon`` raising, or ``post_json`` raising httpx/OS errors) →
    "daemon unavailable"; a non-conflict daemon reply (e.g. 503 store-busy) → "daemon
    error" carrying the status; genuine slug exhaustion after every attempt collided →
    "slug allocation failed".
    """

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
        except (client.DaemonError, httpx.HTTPError, OSError):
            # The POST may have committed server-side before the response was lost
            # (e.g. a timeout after the INSERT), leaving a phantom record the caller
            # never learns the slug of. Best-effort delete it so it can't pad the
            # prune audit forever — the id is stable across attempts. Mirrors the
            # worktree-failure rollback in create_workstream.
            client.delete_workstream(workstream_id)
            return _RecordResult(
                error="daemon unavailable",
                message="The basecamp daemon could not be reached to record the workstream.",
            )
        if result.created:
            return _RecordResult(slug=slug)
        if not result.slug_conflict:
            return _RecordResult(
                error="daemon error",
                message=f"The daemon rejected the workstream (HTTP {result.status}); try again.",
            )
    return _RecordResult(
        error="slug allocation failed",
        message="Could not allocate a unique workstream slug after several tries; try again.",
    )


def _next_step(pane: herdr.HerdrResult, worktree_path: str) -> str:
    if pane.status == "opened":
        return "Open the new Herdr pane and start Claude there, then run /basecamp:start-workstream."
    return f"cd '{worktree_path}' && claude, then run /basecamp:start-workstream."


def _error(status: str, message: str) -> dict[str, Any]:
    return {"status": "failed", "error": status, "message": message}
