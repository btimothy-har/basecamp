"""Render resolved awareness into MCP-facing text.

The ``instructions`` string is the <=2KB router injected into the system prompt
at session start; the resource bodies carry the detail. All text is clean,
project-facing guidance (no runtime/tooling jargon) — the MCP client already
attributes it to the ``basecamp`` server, so the copy stays about the project.
"""

from __future__ import annotations

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
