"""Canonical ``<org>/<name>`` repo identity for the Claude foundation.

Thin wrapper over :mod:`basecamp.claude.gitutil` (the shared git runner + remote
parser): only recognized remote forms (``scheme://…`` or ``user@host:…``) yield an
``<org>/<name>``; a bare filesystem-path origin falls through to the git toplevel
basename, so a plain ``claude`` session in any repo is still named.
"""

from __future__ import annotations

import os

from basecamp.claude.gitutil import parse_remote_identity, run_git


def repo_identity(cwd: str) -> str | None:
    """Best-effort canonical ``<org>/<name>`` for the git repo containing ``cwd``.

    Returns ``None`` when ``cwd`` is not inside a git repository.
    """
    toplevel = run_git(cwd, "rev-parse", "--show-toplevel")
    if not toplevel:
        return None
    origin = run_git(cwd, "remote", "get-url", "origin")
    identity = parse_remote_identity(origin) if origin else None
    return identity or _basename(toplevel)


def repo_root(cwd: str) -> str | None:
    """Return the git top-level directory containing ``cwd``, or ``None`` if not a repo."""
    return run_git(cwd, "rev-parse", "--show-toplevel")


def _basename(path: str) -> str | None:
    return os.path.basename(path.rstrip("/")) or None
