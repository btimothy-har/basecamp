"""Resolve shared-Logseq repo memory for the Claude foundation.

Mirrors the (retired) Pi extension's ``pi/core/project/logseq.ts`` so the Claude
plugin locates the repo cockpit and work dossiers identically — but is a full
parallel: it reads the graph dir from the Claude config (``~/.claude/basecamp.json``,
``logseq.graph_dir``) and derives identity via :mod:`basecamp.claude.identity`,
with no dependency on the ``~/.pi`` config or the MCP awareness resolver.

Memory lives in one shared Logseq graph. This module *locates* the pages — the
cockpit page (whose body it reads into ``cockpit_text``) and the work-dossier
paths — so the renderers stay pure. Dossier bodies are never read here; copilot
Reads a specific dossier itself.

Resolution matches ``logseq.ts`` / ``host/config.ts``: the graph dir resolves
``~``/relative → home (never cwd) and must be an existing directory; the safe
identity transform is ``/`` → ``__`` then non ``[A-Za-z0-9._-]`` → ``_``.

Like the rest of the foundation, this has no daemon dependency — repo-memory
resolution works even when the daemon is down.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from basecamp.claude.config import ClaudeConfig
from basecamp.claude.identity import repo_identity

_LOGSEQ_SECTION = "logseq"
_GRAPH_DIR_KEY = "graph_dir"

_UNSAFE_IDENTITY_RE = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class MemoryAwareness:
    """Resolved shared-Logseq repo-memory locations for the session."""

    graph_dir: str | None = None
    identity: str | None = None
    cockpit_name: str | None = None
    cockpit_path: str | None = None
    cockpit_text: str | None = None
    dossier_prefix: str | None = None
    dossier_paths: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def available(self) -> bool:
        """Whether both a graph dir and a repo identity resolved."""
        return self.graph_dir is not None and self.identity is not None


def safe_identity(identity: str) -> str:
    """Sanitise ``<org>/<name>`` into a Logseq page-name segment.

    Ports ``logseq.ts`` ``safeRepoIdentity``: trim, ``/`` → ``__``, then any
    character outside ``[A-Za-z0-9._-]`` → ``_``.
    """
    collapsed = identity.strip().replace("/", "__")
    return _UNSAFE_IDENTITY_RE.sub("_", collapsed)


def resolve_config_path(directory: str, home: Path) -> str:
    """Resolve a config directory the way ``host/config.ts`` does.

    ``~`` → home; ``~/x`` → home/x; absolute → unchanged; relative → joined onto
    home (never cwd).
    """
    if directory == "~":
        return str(home)
    if directory.startswith("~/"):
        return str(home / directory[2:])
    if os.path.isabs(directory):
        return directory
    return str(home / directory)


def _read_graph_dir(config: ClaudeConfig, home: Path) -> str | None:
    section = config.get_section(_LOGSEQ_SECTION)
    raw = section.get(_GRAPH_DIR_KEY)
    if not isinstance(raw, str) or not raw.strip():
        return None
    resolved = resolve_config_path(raw.strip(), home)
    return resolved if os.path.isdir(resolved) else None


def _read_cockpit(path: Path) -> str | None:
    try:
        text = path.read_text()
    except OSError:
        return None
    return text if text.strip() else None


def _dossier_paths(pages_dir: Path, prefix: str) -> tuple[str, ...]:
    try:
        matches = sorted(pages_dir.glob(f"{prefix}*.md"))
    except OSError:
        return ()
    return tuple(str(path) for path in matches)


def resolve_memory(
    cwd: str,
    *,
    home: Path | None = None,
    config: ClaudeConfig | None = None,
) -> MemoryAwareness:
    """Resolve shared-Logseq repo-memory locations for a working directory."""
    resolved_home = home or Path.home()
    active = config or ClaudeConfig(home=resolved_home)

    identity = repo_identity(cwd)
    if identity is None:
        return MemoryAwareness(reason="repo identity is unavailable")

    graph_dir = _read_graph_dir(active, resolved_home)
    if graph_dir is None:
        return MemoryAwareness(
            identity=identity,
            reason="Logseq graph directory is not configured or does not exist",
        )

    pages_dir = Path(graph_dir) / "pages"
    safe = safe_identity(identity)
    cockpit_name = f"repo__{safe}"
    cockpit_path = pages_dir / f"{cockpit_name}.md"
    dossier_prefix = f"work__{safe}__"
    return MemoryAwareness(
        graph_dir=graph_dir,
        identity=identity,
        cockpit_name=cockpit_name,
        cockpit_path=str(cockpit_path),
        cockpit_text=_read_cockpit(cockpit_path),
        dossier_prefix=dossier_prefix,
        dossier_paths=_dossier_paths(pages_dir, dossier_prefix),
    )
