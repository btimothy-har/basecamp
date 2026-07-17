"""Render resolved awareness into MCP-facing text.

The ``instructions`` string is the <=2KB router injected into the system prompt
at session start; the resource bodies carry the detail. All text is clean,
project-facing guidance (no runtime/tooling jargon) — the MCP client already
attributes it to the ``basecamp`` server, so the copy stays about the project.
"""

from __future__ import annotations

from pathlib import Path

from basecamp.mcp.logseq import MemoryAwareness
from basecamp.mcp.resolve import ProjectAwareness

# Claude Code truncates injected MCP instructions at ~2KB; stay comfortably under.
_INSTRUCTIONS_BUDGET = 1900
_MAX_INLINE_DIRS = 12

_UNPROJECTED_INSTRUCTIONS = (
    "# basecamp\n\n"
    "No basecamp project is configured for the current directory, so no "
    "project-specific context or related directories are available. Work with "
    "the repository in front of you as usual."
)


def build_instructions(awareness: ProjectAwareness) -> str:
    """Build the injected system-prompt router (project identity + dir list + pointers)."""
    if not awareness.projected:
        return _UNPROJECTED_INSTRUCTIONS

    identity = f"You are working in the {awareness.project_name} project"
    identity += f", rooted at {awareness.repo_root}." if awareness.repo_root else "."
    lines = [f"# Project: {awareness.project_name}", "", identity]

    if awareness.related_dirs:
        shown = awareness.related_dirs[:_MAX_INLINE_DIRS]
        remainder = len(awareness.related_dirs) - len(shown)
        lines += [
            "",
            "This project's working set includes directories outside the main",
            "repository. Read from them freely for cross-cutting context; treat",
            "them as part of the same project.",
            "",
            "Related directories:",
            *(f"- {directory}" for directory in shown),
        ]
        if remainder > 0:
            lines.append(f"- ...and {remainder} more; see basecamp://project/dirs")

    lines += [
        "",
        "Before substantive work, read the project's standing guidance:",
        "- basecamp://project/context - conventions and standing context",
        "- basecamp://project/dirs - the full related-directory list",
    ]
    return _trim_to_budget("\n".join(lines))


def _trim_to_budget(text: str) -> str:
    if len(text.encode("utf-8")) <= _INSTRUCTIONS_BUDGET:
        return text
    lines = text.split("\n")
    while lines and len("\n".join(lines).encode("utf-8")) > _INSTRUCTIONS_BUDGET:
        lines.pop()
    return "\n".join(lines)


def render_dirs(awareness: ProjectAwareness) -> str:
    """Render the ``basecamp://project/dirs`` resource body."""
    lines = ["# Related directories"]
    if awareness.repo_root:
        lines += ["", f"Repository root: {awareness.repo_root}"]
    if awareness.related_dirs:
        lines += ["", "Additional working directories (existing, resolved):"]
        lines += [f"- {directory}" for directory in awareness.related_dirs]
        lines += ["", "Paths configured but not currently present are omitted."]
    else:
        lines += ["", "No additional directories are configured for this project."]
    return "\n".join(lines)


def render_context(awareness: ProjectAwareness) -> str:
    """Render the ``basecamp://project/context`` resource body."""
    if awareness.context_text is not None:
        return awareness.context_text
    name = awareness.project_name or "this directory"
    return f"No standing project context is configured for {name}."


def _memory_unavailable(memory: MemoryAwareness) -> str:
    reason = memory.reason or "durable repo memory is unavailable"
    return "\n".join(
        [
            "# Repo memory",
            "",
            "Durable repo memory is unavailable for this session; copilot remains usable without it.",
            f"Reason: {reason}.",
            f"Configured graph path: {memory.graph_dir or 'unavailable'}",
            f"Repo identity: {memory.repo_identity or 'unavailable'}",
            "",
            "Continue without durable repo memory. Do not scan the Logseq graph to compensate.",
        ]
    )


def render_cockpit(memory: MemoryAwareness) -> str:
    """Render the ``basecamp://memory/cockpit`` resource body.

    The repo cockpit page body if present; otherwise a seed stub telling copilot
    where to start it. Falls back to the unavailable body when memory is not
    resolvable (no graph dir or no repo identity).
    """
    if not memory.available or memory.cockpit_path is None:
        return _memory_unavailable(memory)

    try:
        body = Path(memory.cockpit_path).read_text()
    except OSError:
        body = ""
    if body.strip():
        return body

    return "\n".join(
        [
            f"# {memory.cockpit_name}",
            "",
            f"The repo cockpit for {memory.repo_identity} is not written yet.",
            f"Seed it at `{memory.cockpit_path}` when durable repo-level context is worth keeping:",
            "current focus, priority shifts, the active/waiting/blocked/stale/proposed/not-now",
            "choice-set, and cross-workstream decisions.",
            "",
            "Read the cockpit first when durable repo context matters. Do not scan the whole graph.",
        ]
    )


def render_dossier_index(memory: MemoryAwareness) -> str:
    """Render the ``basecamp://memory/dossiers`` resource body.

    A pointer index (slug + path) of the repo's work dossiers — never the
    dossier bodies. Copilot Reads a specific dossier itself when a task calls
    for it.
    """
    if not memory.available or memory.dossier_prefix is None:
        return _memory_unavailable(memory)

    lines = [f"# Work dossiers for {memory.repo_identity}", ""]
    if not memory.dossier_paths:
        lines += [
            "No work dossiers exist yet.",
            f"They are pages named `{memory.dossier_prefix}<slug>` in the shared Logseq graph.",
        ]
        return "\n".join(lines)

    lines.append("Open only a specifically relevant dossier; do not read them all.")
    lines.append("")
    for path in memory.dossier_paths:
        slug = _dossier_slug(path, memory.dossier_prefix)
        lines.append(f"- {slug} — `{path}`")
    return "\n".join(lines)


def _dossier_slug(path: str, prefix: str) -> str:
    stem = Path(path).stem
    return stem[len(prefix) :] if stem.startswith(prefix) else stem
