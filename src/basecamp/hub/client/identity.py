"""Derive a session's :class:`RegisterFrame` from hook stdin + environment.

Mirrors the connector's ``identity.ts`` field-for-field, adapted to Claude Code:
``node_id`` is the session id (``CLAUDE_CODE_SESSION_ID`` / hook stdin), and the
env chain (``BASECAMP_*``) still drives role/depth/parent when a daemon-spawned
worker sets it. ``repo`` falls back to a git-origin derivation so a plain
``claude`` session — which has no launcher setting ``BASECAMP_REPO`` — is still
identified by its canonical ``<org>/<name>``.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping

from ..frames import RegisterFrame

# Bounded so a slow/hung git never stacks toward the SessionStart hook timeout:
# two sequential calls (origin + toplevel) plus ensure_daemon's 5s budget must
# stay well under the 15s hook cap. Local git config/toplevel reads are ~instant;
# this is only a safety ceiling.
_GIT_TIMEOUT_S = 3
_SSH_REMOTE = re.compile(r"^[^@]+@[^:]+:(?P<path>.+)$")


def resolve_node_id(session_id: str, env: Mapping[str, str] | None = None) -> str:
    """The daemon key for a session: ``BASECAMP_AGENT_ID`` if set, else the session id.

    Single-sourced so the SessionStart register and the SessionEnd deregister key
    the same row — a daemon-spawned worker whose ``BASECAMP_AGENT_ID`` differs from
    the native session id must be *ended* under the same id it *registered* under.
    """

    environ = env if env is not None else os.environ
    return _clean(environ.get("BASECAMP_AGENT_ID")) or session_id


def build_register_frame(
    *,
    session_id: str,
    cwd: str,
    transcript_path: str | None,
    env: Mapping[str, str] | None = None,
) -> RegisterFrame:
    """Build the register frame for a Claude Code session."""

    environ = env if env is not None else os.environ
    node_id = resolve_node_id(session_id, environ)
    role = "worker" if environ.get("BASECAMP_USER_FACING") == "0" else "agent"
    repo = _clean(environ.get("BASECAMP_REPO")) or _derive_repo(cwd)
    worktree_label = _clean(environ.get("BASECAMP_WORKTREE_LABEL"))
    session_name = _clean(environ.get("BASECAMP_SESSION_NAME")) or worktree_label or repo or _basename(cwd) or node_id
    return RegisterFrame(
        type="register",
        role=role,
        node_id=node_id,
        agent_handle=None,
        parent_id=_clean(environ.get("BASECAMP_PARENT_SESSION")),
        sibling_group=_clean(environ.get("BASECAMP_SIBLING_GROUP")),
        depth=_safe_depth(environ.get("BASECAMP_AGENT_DEPTH")),
        session_name=session_name,
        cwd=cwd,
        session_file=transcript_path or None,
        repo=repo,
        worktree_label=worktree_label,
    )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _basename(path: str) -> str | None:
    return os.path.basename(path.rstrip("/")) or None


def _safe_depth(raw: str | None) -> int:
    try:
        depth = int(raw) if raw is not None else 0
    except ValueError:
        return 0
    return depth if depth >= 0 else 0


def _derive_repo(cwd: str) -> str | None:
    """Canonical ``<org>/<name>`` from the git origin, else the toplevel basename."""

    origin = _git(cwd, "remote", "get-url", "origin")
    identity = _parse_repo_identity(origin) if origin else None
    if identity:
        return identity
    toplevel = _git(cwd, "rev-parse", "--show-toplevel")
    return _basename(toplevel) if toplevel else None


def _parse_repo_identity(url: str) -> str | None:
    """Canonical ``<org>/<name>`` from a *remote URL* (scheme:// or scp form), else None.

    Only recognized remote forms yield an identity; a bare filesystem-path origin
    returns None so :func:`_derive_repo` falls through to the toplevel basename —
    matching ``workspace.cli.environment.derive_repo_identity`` (which returns its
    fallback for non-URL origins) rather than treating path tail segments as org/name.
    """

    text = url.strip()
    if text.startswith(("http://", "https://", "ssh://", "git://")):
        path = re.sub(r"^[a-z]+://", "", text)
        path = path.split("/", 1)[1] if "/" in path else ""
    else:
        match = _SSH_REMOTE.match(text)
        if match is None:
            return None
        path = match.group("path")
    path = path.removesuffix(".git").strip("/")
    parts = [segment for segment in path.split("/") if segment]
    if len(parts) < 2:
        return None
    return "/".join(parts[-2:])


def _git(cwd: str, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
