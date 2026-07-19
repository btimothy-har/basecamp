"""Derive a session's register body from hook stdin + environment.

The session's identity is the native ``session_id`` (from ``CLAUDE_CODE_SESSION_ID``
/ hook stdin) — there is no ``BASECAMP_AGENT_ID`` indirection or worker re-keying
on the Claude path (that was a Pi swarm concept). ``repo`` falls back to a
git-origin derivation so a plain ``claude`` session — which has no launcher
setting ``BASECAMP_REPO`` — is still identified by its canonical ``<org>/<name>``.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping

from ..contract import SessionRegisterBody

# Bounded so a slow/hung git never stacks toward the SessionStart hook timeout:
# two sequential calls (origin + toplevel) plus ensure_daemon's 5s budget must
# stay well under the 15s hook cap. Local git config/toplevel reads are ~instant;
# this is only a safety ceiling.
_GIT_TIMEOUT_S = 3
_SSH_REMOTE = re.compile(r"^[^@]+@[^:]+:(?P<path>.+)$")


def build_register_body(
    *,
    session_id: str,
    cwd: str,
    transcript_path: str | None,
    source: str | None = None,
    env: Mapping[str, str] | None = None,
) -> SessionRegisterBody:
    """Build the register body for a Claude Code session."""

    environ = env if env is not None else os.environ
    repo = _clean(environ.get("BASECAMP_REPO")) or _derive_repo(cwd)
    worktree_label = _clean(environ.get("BASECAMP_WORKTREE_LABEL"))
    return SessionRegisterBody(
        session_id=session_id,
        cwd=cwd,
        transcript_path=transcript_path or None,
        repo=repo,
        worktree_label=worktree_label,
        handle=None,
        source=source,
    )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _basename(path: str) -> str | None:
    return os.path.basename(path.rstrip("/")) or None


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
    # Drop empty and traversal segments so a crafted/mistyped origin like
    # ".../../.ssh" can't register a "../…" repo identity in the daemon store
    # (mirrors basecamp.claude.gitutil.parse_remote_identity, the launcher copy).
    parts = [segment for segment in path.split("/") if segment and segment not in (".", "..")]
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
