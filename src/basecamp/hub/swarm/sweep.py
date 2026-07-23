"""Daemon-side periodic backstop sweep for agent worktrees.

Mirrors ``pi/core/git/worktrees/sweep.ts`` (issue #310 Phase 2): the daemon becomes the
sole owner of agent-worktree teardown by running a periodic sweep that reclaims
integrated, detached, and age-stale locked agent residue — so a never-restarted daemon
cannot leak agent workspaces.  Session worktrees (``wt-*``, ``copilot/*``, direct labels)
are handled entirely in TypeScript and are always ignored here.

Coverage (categories from sweep.ts):

1.  **Integrated agent worktrees** — a worktree whose branch is a recognized agent branch
    AND is an ancestor of some non-agent checked-out branch → unlock if locked, force-remove,
    delete the branch.
2.  **Detached agent report/ask residue** — a branchless worktree whose path matches
    ``<WORKTREES_ROOT>/<identity>/agent-<token>/<name>`` → force-remove (no branch to delete).
3.  **Age-stale locked agent residue** — lock reason ``basecamp agent run <ISO ts>`` older
    than 24h → unlock + remove per the rules above.  A fresh lock (< 24h) means a live run
    holds it → SKIP.
4.  **Orphan integrated ``agent/*`` branches** with no worktree → delete once integrated.
    Unintegrated agent branches are always kept.

All git operations are strictly local (no network, no fetch/prune).  The sweep is
best-effort: OSError and SubprocessError are suppressed so it never crashes the daemon.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime

AGENT_BRANCH_NAMESPACE = "agent/"
LEGACY_AGENT_BRANCH_RE = re.compile(r"^agent-[a-z0-9]+/")
AGENT_LABEL_DIR_RE = re.compile(r"^agent-[a-z0-9]+$")
AGENT_LOCK_REASON_PREFIX = "basecamp agent run "
STALE_LOCK_SECONDS = 24 * 60 * 60

_GIT_SHORT_TIMEOUT = 15
_GIT_LONG_TIMEOUT = 30


@dataclass
class WorktreeRecord:
    """One entry from ``git worktree list --porcelain``."""

    path: str
    branch: str | None = None
    locked: bool = False
    lock_reason: str | None = None


@dataclass
class SweepResult:
    """Outcome of one sweep pass."""

    removed: list[str] = field(default_factory=list)
    kept: int = 0


def _worktrees_root() -> str:
    return os.path.join(os.path.expanduser("~"), ".worktrees")


def is_agent_branch(branch: str | None) -> bool:
    """True for ``agent/<handle>`` (current) or ``agent-<token>/<name>`` (legacy)."""
    if not branch:
        return False
    return branch.startswith(AGENT_BRANCH_NAMESPACE) or bool(LEGACY_AGENT_BRANCH_RE.match(branch))


def is_agent_workspace_path(wt_path: str, identity_root: str) -> bool:
    """True when *wt_path* is exactly ``<identity_root>/agent-<token>/<name>``.

    The identity root may be one or two path segments (``<repo>`` or ``<org>/<repo>``);
    the label must be the two-segment ``agent-<token>/<name>`` shape relative to it.
    """
    relative = os.path.relpath(os.path.abspath(wt_path), os.path.abspath(identity_root))
    if relative.startswith("..") or os.path.isabs(relative):
        return False
    segments = relative.split(os.sep)
    return len(segments) == 2 and bool(AGENT_LABEL_DIR_RE.match(segments[0]))


def _agent_lock_age_seconds(lock_reason: str | None, now: float) -> float | None:
    """Age in seconds of an agent-run lock, or None when foreign/untimestamped."""
    if not lock_reason or not lock_reason.startswith(AGENT_LOCK_REASON_PREFIX):
        return None
    timestamp = lock_reason[len(AGENT_LOCK_REASON_PREFIX) :].strip()
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    return now - parsed.timestamp()


def _is_stale_lock(lock_reason: str | None, now: float) -> bool:
    """True only when the lock is a provably-stale agent-run lock (≥ 24h old)."""
    age = _agent_lock_age_seconds(lock_reason, now)
    return age is not None and age >= STALE_LOCK_SECONDS


def _run_git(args: list[str], *, timeout: int = _GIT_SHORT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)


def _parse_worktree_list(output: str) -> list[WorktreeRecord]:
    """Parse ``git worktree list --porcelain`` output into records."""
    records: list[WorktreeRecord] = []
    current: WorktreeRecord | None = None

    for line in f"{output}\n".split("\n"):
        if not line.strip():
            if current is not None:
                records.append(current)
                current = None
            continue
        if line.startswith("worktree "):
            if current is not None:
                records.append(current)
            current = WorktreeRecord(path=line[len("worktree ") :])
        elif current is not None and line.startswith("branch "):
            ref = line[len("branch ") :]
            current.branch = ref[len("refs/heads/") :] if ref.startswith("refs/heads/") else ref
        elif current is not None and (line == "locked" or line.startswith("locked ")):
            current.locked = True
            current.lock_reason = None if line == "locked" else line[len("locked ") :]

    return records


def _resolve_main_checkout(worktree_path: str) -> str | None:
    """Resolve the common git dir's parent (the main checkout) for a worktree path.

    A worktree cannot remove itself; operations must run from the main checkout.
    Returns None when the worktree is gone or not a git worktree.
    """
    try:
        result = _run_git(
            ["git", "-C", worktree_path, "rev-parse", "--path-format=absolute", "--git-common-dir"],
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return os.path.dirname(result.stdout.strip())


def _is_ancestor(repo_root: str, branch: str, candidate: str) -> bool:
    """True when *branch* is an ancestor of *candidate* (merged into it)."""
    try:
        result = _run_git(
            ["git", "-C", repo_root, "merge-base", "--is-ancestor", branch, candidate],
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _is_integrated(repo_root: str, branch: str, candidates: list[str]) -> bool:
    return any(_is_ancestor(repo_root, branch, c) for c in candidates)


def _unlock(repo_root: str, wt_path: str) -> None:
    try:
        _run_git(["git", "-C", repo_root, "worktree", "unlock", wt_path])
    except (OSError, subprocess.SubprocessError):
        pass


def _remove_worktree(repo_root: str, wt_path: str) -> None:
    try:
        _run_git(
            ["git", "-C", repo_root, "worktree", "remove", "--force", wt_path],
            timeout=_GIT_LONG_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _delete_branch(repo_root: str, branch: str) -> None:
    try:
        _run_git(["git", "-C", repo_root, "branch", "-D", branch])
    except (OSError, subprocess.SubprocessError):
        pass


def _list_branches(repo_root: str) -> list[str]:
    try:
        result = _run_git(["git", "-C", repo_root, "branch", "--format=%(refname:short)"])
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.split("\n") if line.strip()]


def _iter_identity_dirs(worktrees_root: str):
    """Yield identity root directories (one or two path segments under the root)."""
    try:
        top_entries = sorted(os.listdir(worktrees_root))
    except OSError:
        return
    for name in top_entries:
        single = os.path.join(worktrees_root, name)
        if not os.path.isdir(single):
            continue
        yield single
        # Two-segment identity: <org>/<repo>
        try:
            sub_entries = sorted(os.listdir(single))
        except OSError:
            continue
        for sub_name in sub_entries:
            nested = os.path.join(single, sub_name)
            if os.path.isdir(nested):
                yield nested


def _iter_worktree_leaf_dirs(identity_root: str):
    """Yield candidate worktree directories under an identity root.

    Labels may be direct (one segment), ``wt-xx/name``, ``copilot/name``, or
    ``agent-<token>/<name>`` (two segments).  Any existing directory that could be a
    worktree is yielded so we can resolve its main checkout.
    """
    try:
        entries = sorted(os.listdir(identity_root))
    except OSError:
        return
    for name in entries:
        child = os.path.join(identity_root, name)
        if os.path.isdir(child):
            yield child
            try:
                sub_entries = sorted(os.listdir(child))
            except OSError:
                continue
            for sub_name in sub_entries:
                leaf = os.path.join(child, sub_name)
                if os.path.isdir(leaf):
                    yield leaf


def _discover_main_checkouts(worktrees_root: str) -> list[str]:
    """Walk *worktrees_root* on disk to find distinct main checkouts.

    The daemon is host-global and has no repo registry, so it discovers repos by
    resolving the common git dir of any worktree directory that still exists on disk.
    Crashed-daemon residue has no live record, so the sweep must catch orphans purely
    from the filesystem + git state.
    """
    main_checkouts: set[str] = set()
    if not os.path.isdir(worktrees_root):
        return []

    for identity_root in _iter_identity_dirs(worktrees_root):
        for wt_path in _iter_worktree_leaf_dirs(identity_root):
            main = _resolve_main_checkout(wt_path)
            if main is not None:
                main_checkouts.add(main)

    return sorted(main_checkouts)


def _is_agent_workspace_under_root(wt_path: str, worktrees_root: str) -> bool:
    """True when a branchless worktree path matches the agent workspace shape.

    The identity under *worktrees_root* may be one or two path segments; the label
    must be exactly ``agent-<token>/<name>`` relative to the identity root.
    """
    abs_path = os.path.abspath(wt_path)
    abs_root = os.path.abspath(worktrees_root)
    relative = os.path.relpath(abs_path, abs_root)
    if relative.startswith("..") or os.path.isabs(relative):
        return False
    segments = relative.split(os.sep)
    # <identity>/agent-<token>/<name> — identity is 1 or 2 segments, label is 2.
    for identity_len in (1, 2):
        if len(segments) == identity_len + 2:
            label_dir = segments[identity_len]
            if AGENT_LABEL_DIR_RE.match(label_dir):
                return True
    return False


def _sweep_orphan_branches(repo_root: str, checked_out: set[str | None], integration_branches: list[str]) -> None:
    """Delete integrated agent branches that have no worktree (orphans)."""
    for branch in _list_branches(repo_root):
        if not is_agent_branch(branch) or branch in checked_out:
            continue
        if _is_integrated(repo_root, branch, integration_branches):
            _delete_branch(repo_root, branch)


def _sweep_repo(
    repo_root: str,
    records: list[WorktreeRecord],
    worktrees_root: str,
    now: float,
) -> tuple[list[str], int]:
    """Apply the four sweep rules to one repo's worktree records.

    Returns (removed_paths, kept_count).
    """
    # Integration candidates: every non-agent checked-out branch.
    integration_branches = [r.branch for r in records if r.branch is not None and not is_agent_branch(r.branch)]
    checked_out = {r.branch for r in records if r.branch is not None}

    # Orphan agent branches (no worktree) are swept regardless of whether any agent
    # worktree records remain — a repo whose only agent worktree was already removed
    # can still hold an orphan integrated branch.
    _sweep_orphan_branches(repo_root, checked_out, integration_branches)

    agent_records = [
        r
        for r in records
        if is_agent_branch(r.branch) or (r.branch is None and _is_agent_workspace_under_root(r.path, worktrees_root))
    ]
    if not agent_records:
        return [], 0

    removed: list[str] = []
    for record in agent_records:
        integrated = _is_integrated(repo_root, record.branch, integration_branches) if record.branch else False
        # Reclaimable: integrated branch, or branchless (detached report/ask residue).
        if record.branch is not None and not integrated:
            continue

        if record.locked:
            # A live run holds a fresh lock; only provably-stale agent locks may be broken.
            if not _is_stale_lock(record.lock_reason, now):
                continue
            _unlock(repo_root, record.path)

        _remove_worktree(repo_root, record.path)
        removed.append(record.path)
        if record.branch is not None:
            _delete_branch(repo_root, record.branch)

    kept = len(agent_records) - len(removed)
    return removed, kept


def sweep_agent_worktrees(worktrees_root: str | None = None) -> SweepResult:
    """Run one backstop sweep pass over all discovered repos.

    Best-effort: OSError and SubprocessError are suppressed so the sweep never
    crashes the daemon.  Returns a summary of removed paths and kept count.
    """
    root = worktrees_root or _worktrees_root()
    now = datetime.now(UTC).timestamp()
    all_removed: list[str] = []
    total_kept = 0

    for repo_root in _discover_main_checkouts(root):
        try:
            result = _run_git(
                ["git", "-C", repo_root, "worktree", "list", "--porcelain"],
                timeout=_GIT_LONG_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0:
            continue
        records = _parse_worktree_list(result.stdout)
        try:
            removed, kept = _sweep_repo(repo_root, records, root, now)
        except (OSError, subprocess.SubprocessError):
            continue
        all_removed.extend(removed)
        total_kept += kept

    return SweepResult(removed=all_removed, kept=total_kept)


async def run_periodic_sweep(interval_s: float, worktrees_root: str | None = None) -> None:
    """Periodic background task: sweep at *interval_s*, suppressing all errors.

    The first sweep runs after one interval.  Each pass is offloaded to a thread (git
    is blocking) and wrapped so no exception ever escapes — the sweep must never crash
    the daemon.
    """
    while True:
        await asyncio.sleep(interval_s)
        try:
            await asyncio.to_thread(sweep_agent_worktrees, worktrees_root)
        except Exception:  # noqa: BLE001
            pass
