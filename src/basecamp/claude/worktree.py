"""Git worktree provisioning for workstreams (Python parallel of the Pi crud).

A workstream gets a **permanent** worktree at
``~/.worktrees/<org>/<name>/copilot/<slug>/`` on a work-derived branch. This
module is the Python port of the Pi ``core/git/worktrees`` primitives, shelling
out to ``git`` directly (the TS was itself only a thin subprocess wrapper — there
is nothing TS-specific to preserve, and the repo already shells git the same way
in ``companion/diff`` and the client identity code).

Deliberately **no protected-checkout guard**: ``git worktree add`` branches from
the base branch's committed tip, so a dirty main checkout neither corrupts nor
leaks into the new worktree (verified empirically — see the port design doc
§10.1). The clean-worktree check is a copilot-skill courtesy, not a hard gate.

``get_or_create_worktree`` is idempotent by label: an existing registered worktree
at the target path is reused (``created=False``) rather than re-added.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from basecamp.claude.paths import worktrees_root

_GIT_TIMEOUT_S = 30
_LABEL_MAX_LENGTH = 32
_FALLBACK_USER_PREFIX = "un"
_FALLBACK_SLUG = "worktree"


@dataclass(frozen=True)
class WorktreeTarget:
    """The label + branch a workstream worktree is created under."""

    label: str
    branch: str


@dataclass(frozen=True)
class WorktreeResult:
    """A provisioned worktree: its path, label, branch, and whether it was newly created."""

    path: str
    label: str
    branch: str
    created: bool


class WorktreeError(RuntimeError):
    """A git worktree operation failed."""


def _user_prefix(user_id: str) -> str:
    prefix = "".join(ch for ch in user_id.lower() if ch.isalnum())[:2]
    return prefix if len(prefix) == 2 else _FALLBACK_USER_PREFIX


def normalize_slug(value: str) -> str:
    """Lowercase, collapse non-alphanumerics to ``-``, trim; fallback ``worktree``."""
    slug = "".join(ch if ch.isalnum() else "-" for ch in value.lower()).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or _FALLBACK_SLUG


def copilot_worktree_target(work_name: str, slug: str, user_id: str) -> WorktreeTarget:
    """Compute the ``copilot/<slug>`` label and the ``<prefix>/<work-slug>`` branch.

    The label is the generic reusable container (keyed on the workstream ``slug``);
    the branch is derived from ``work_name`` and capped so the whole label stays
    within 32 chars, matching the Pi ``copilotWorktreeTarget``.
    """

    prefix = _user_prefix(user_id)
    branch_prefix = f"{prefix}/"
    max_slug = max(1, _LABEL_MAX_LENGTH - len(branch_prefix))
    capped = normalize_slug(work_name)[:max_slug].rstrip("-") or _FALLBACK_SLUG
    return WorktreeTarget(label=f"copilot/{slug}", branch=f"{branch_prefix}{capped}")


def detect_default_branch(repo_root: str) -> str:
    """Return the repo's default branch (origin/HEAD → main → master)."""
    origin_head = _git(repo_root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if origin_head and origin_head.startswith("origin/"):
        return origin_head[len("origin/") :]
    if _git(repo_root, "rev-parse", "--verify", "main") is not None:
        return "main"
    if _git(repo_root, "rev-parse", "--verify", "master") is not None:
        return "master"
    msg = "could not determine default branch (expected origin/HEAD, main, or master)"
    raise WorktreeError(msg)


def branch_exists(repo_root: str, branch: str) -> bool:
    """Whether a local branch ``refs/heads/<branch>`` exists."""
    return _git(repo_root, "rev-parse", "--verify", f"refs/heads/{branch}") is not None


def get_or_create_worktree(
    repo_root: str,
    repo: str,
    label: str,
    branch: str,
    *,
    home: Path | None = None,
) -> WorktreeResult:
    """Create (or reuse by label) the worktree at ``~/.worktrees/<repo>/<label>``.

    Idempotent: if git already knows a worktree at the target path, it is reused
    (``created=False``). Otherwise ``git worktree add`` creates it — reusing an
    existing branch, or branching a fresh one off the default branch.
    """

    worktree_dir = worktrees_root(home) / repo / label
    resolved = str(worktree_dir)

    if _worktree_registered(repo_root, resolved):
        return WorktreeResult(path=resolved, label=label, branch=branch, created=False)
    if worktree_dir.exists():
        msg = f"worktree path exists but is not registered with git: {resolved}"
        raise WorktreeError(msg)

    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    if branch_exists(repo_root, branch):
        args = ["worktree", "add", resolved, branch]
    else:
        default_branch = detect_default_branch(repo_root)
        args = ["worktree", "add", "-b", branch, resolved, default_branch]
    if _git(repo_root, *args) is None:
        msg = f"failed to create worktree at {resolved}"
        raise WorktreeError(msg)
    return WorktreeResult(path=resolved, label=label, branch=branch, created=True)


def _worktree_registered(repo_root: str, worktree_path: str) -> bool:
    """Whether ``git worktree list`` records a worktree at ``worktree_path``."""
    listing = _git(repo_root, "worktree", "list", "--porcelain")
    if not listing:
        return False
    target = str(Path(worktree_path).resolve())
    for line in listing.splitlines():
        if line.startswith("worktree "):
            recorded = str(Path(line[len("worktree ") :].strip()).resolve())
            if recorded == target:
                return True
    return False


def _git(repo_root: str, *args: str) -> str | None:
    """Run ``git -C <repo_root> <args>``; return stdout on success, ``None`` on failure."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_root, *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()
