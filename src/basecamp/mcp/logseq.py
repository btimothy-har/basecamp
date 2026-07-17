"""Resolve shared-Logseq repo memory for the basecamp MCP context server.

Mirrors the (retired) Pi extension's ``pi/core/project/logseq.ts`` so the Claude
Code plugin locates the repo cockpit and work dossiers identically. Memory lives
in one shared Logseq graph (config key ``logseq.graph_dir``); this module only
*locates* the pages — the cockpit page and the work-dossier glob — and never
reads dossier bodies (copilot Reads a specific dossier itself).

Resolution matches ``logseq.ts`` / ``host/config.ts`` exactly: the graph dir is
resolved ``~``/relative → home (never cwd) and must be an existing directory;
the repo identity is the canonical ``<org>/<name>`` (reusing
:func:`derive_repo_identity`, so page names cannot drift from other
derivations), sanitised by :func:`safe_repo_identity` (``/`` → ``__``, other
non ``[A-Za-z0-9._-]`` → ``_``).

Like the awareness resolver, this has no dependency on the basecamp daemon —
repo memory resources work even when the daemon is down.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from basecamp.core.settings import Settings
from basecamp.mcp.resolve import resolve_config_dir
from basecamp.workspace.cli.environment import derive_repo_identity

_LOGSEQ_SECTION = "logseq"
_GRAPH_DIR_KEY = "graph_dir"
_GIT_TIMEOUT_SECONDS = 5

_UNSAFE_IDENTITY_RE = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class MemoryAwareness:
    """Resolved shared-Logseq repo-memory locations for the session."""

    graph_dir: str | None = None
    repo_identity: str | None = None
    cockpit_name: str | None = None
    cockpit_path: str | None = None
    dossier_prefix: str | None = None
    dossier_paths: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def available(self) -> bool:
        """Whether both a graph dir and a repo identity resolved."""
        return self.graph_dir is not None and self.repo_identity is not None


def safe_repo_identity(repo_identity: str) -> str:
    """Sanitise ``<org>/<name>`` into a Logseq page-name segment.

    Ports ``logseq.ts`` ``safeRepoIdentity``: trim, ``/`` → ``__``, then any
    character outside ``[A-Za-z0-9._-]`` → ``_``.
    """
    collapsed = repo_identity.strip().replace("/", "__")
    return _UNSAFE_IDENTITY_RE.sub("_", collapsed)


def _read_graph_dir(config: Settings | None, home: Path) -> str | None:
    """Resolve ``logseq.graph_dir`` to an existing directory, or ``None``.

    Mirrors ``host/config.ts`` ``readLogseqGraphDir``: read the section, take
    ``graph_dir`` if it is a non-empty string, resolve it (``~``/relative →
    home), and require it to be an existing directory.
    """
    active = config or Settings()
    section = active.get_section(_LOGSEQ_SECTION)
    raw = section.get(_GRAPH_DIR_KEY)
    if not isinstance(raw, str) or not raw.strip():
        return None
    resolved = resolve_config_dir(raw.strip(), home)
    return resolved if os.path.isdir(resolved) else None


def _repo_identity(cwd: str) -> str | None:
    """Best-effort canonical ``<org>/<name>`` identity for ``cwd``'s repo."""
    top = _git(cwd, "rev-parse", "--show-toplevel")
    if not top:
        return None
    remote = _git(cwd, "remote", "get-url", "origin")
    return derive_repo_identity(remote, Path(top).name)


def _git(cwd: str, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _dossier_paths(pages_dir: Path, prefix: str) -> tuple[str, ...]:
    try:
        matches = sorted(pages_dir.glob(f"{prefix}*.md"))
    except OSError:
        return ()
    return tuple(str(path) for path in matches)


def resolve_memory(cwd: str, *, home: Path | None = None, config: Settings | None = None) -> MemoryAwareness:
    """Resolve shared-Logseq repo-memory locations for a working directory."""
    resolved_home = home or Path.home()

    repo_identity = _repo_identity(cwd)
    if repo_identity is None:
        return MemoryAwareness(reason="repo identity is unavailable")

    graph_dir = _read_graph_dir(config, resolved_home)
    if graph_dir is None:
        return MemoryAwareness(
            repo_identity=repo_identity,
            reason="Logseq graph directory is not configured or does not exist",
        )

    pages_dir = Path(graph_dir) / "pages"
    safe = safe_repo_identity(repo_identity)
    cockpit_name = f"repo__{safe}"
    dossier_prefix = f"work__{safe}__"
    return MemoryAwareness(
        graph_dir=graph_dir,
        repo_identity=repo_identity,
        cockpit_name=cockpit_name,
        cockpit_path=str(pages_dir / f"{cockpit_name}.md"),
        dossier_prefix=dossier_prefix,
        dossier_paths=_dossier_paths(pages_dir, dossier_prefix),
    )
