"""Shared git helpers for the Claude foundation.

One home for the small git plumbing the foundation's ``identity`` and ``worktree``
modules both need — the subprocess runner and the remote-URL → ``<org>/<name>``
parser — so they can't drift. Kept inside ``basecamp.claude`` (the isolated
``hub/claude`` daemon path keeps its own copy on purpose, to stay self-contained
and promotable).

``run_git`` returns stripped stdout on success, or ``None`` on any failure
(non-zero exit, spawn error, or empty output). Callers that must distinguish
"ran, no output" from "failed" do not exist here — every consumer treats an empty
result as absence.
"""

from __future__ import annotations

import re
import subprocess

#: Default git timeout. Bounded so a slow/hung git never stalls a resource fetch or
#: a hook; local reads are ~instant, so this is only a safety ceiling. ``worktree``
#: operations pass a longer timeout for ``worktree add``.
DEFAULT_GIT_TIMEOUT_S = 5

_SSH_REMOTE = re.compile(r"^[^@]+@[^:]+:(?P<path>.+)$")
_URL_SCHEMES = ("http://", "https://", "ssh://", "git://")


def run_git(cwd: str, *args: str, timeout: float = DEFAULT_GIT_TIMEOUT_S) -> str | None:
    """Run ``git -C <cwd> <args>``; return stripped stdout, or ``None`` on any failure."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def parse_remote_identity(url: str) -> str | None:
    """Canonical ``<org>/<name>`` from a remote URL, else ``None`` for non-URL origins.

    Recognizes ``scheme://…`` and ``user@host:…`` (scp) forms; a bare filesystem-path
    origin returns ``None`` so callers fall through to a toplevel-basename fallback.
    """
    text = url.strip()
    if text.startswith(_URL_SCHEMES):
        path = re.sub(r"^[a-z]+://", "", text)
        path = path.split("/", 1)[1] if "/" in path else ""
    else:
        match = _SSH_REMOTE.match(text)
        if match is None:
            return None
        path = match.group("path")
    path = path.removesuffix(".git").strip("/")
    # Drop empty and traversal segments: the identity is used as a filesystem path
    # component (scratch dir) downstream, so a crafted origin like ".../../.ssh"
    # must never yield a "../…" identity that escapes its parent.
    parts = [segment for segment in path.split("/") if segment and segment not in (".", "..")]
    if len(parts) < 2:
        return None
    return "/".join(parts[-2:])
