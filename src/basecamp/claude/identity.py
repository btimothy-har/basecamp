"""Canonical ``<org>/<name>`` repo identity for the Claude foundation.

A self-contained parallel to the ``hub/claude`` identity derivation: it owns its
own git plumbing and remote-URL parsing rather than importing the Pi-era
interactive CLI. Only recognized remote forms (``scheme://…`` or ``user@host:…``)
yield an ``<org>/<name>``; a bare filesystem-path origin falls through to the
git toplevel basename, so a plain ``claude`` session in any repo is still named.
"""

from __future__ import annotations

import os
import re
import subprocess

# Bounded so a slow/hung git never stalls a resource fetch; local reads are
# ~instant, so this is only a safety ceiling.
_GIT_TIMEOUT_S = 5
_SSH_REMOTE = re.compile(r"^[^@]+@[^:]+:(?P<path>.+)$")


def repo_identity(cwd: str) -> str | None:
    """Best-effort canonical ``<org>/<name>`` for the git repo containing ``cwd``.

    Returns ``None`` when ``cwd`` is not inside a git repository.
    """
    toplevel = _git(cwd, "rev-parse", "--show-toplevel")
    if not toplevel:
        return None
    origin = _git(cwd, "remote", "get-url", "origin")
    identity = _parse_remote_identity(origin) if origin else None
    return identity or _basename(toplevel)


def _parse_remote_identity(url: str) -> str | None:
    """Canonical ``<org>/<name>`` from a remote URL, else ``None`` for non-URL origins."""
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


def _basename(path: str) -> str | None:
    return os.path.basename(path.rstrip("/")) or None


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
