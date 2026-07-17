"""The basecamp MCP context server (stdio).

Spawned per Claude Code session; inherits the session cwd and resolves the
project once at startup to build the injected ``instructions`` router, then
serves the related-directory and context resources live (re-reading config on
each fetch so edits are picked up without restarting the session).

Awareness is pure config resolution — this server has no dependency on the
basecamp daemon, so project awareness works even when the daemon is down.
"""

from __future__ import annotations

import os
from typing import Any

from basecamp.claude.logseq import resolve_logseq
from basecamp.mcp.render import (
    build_instructions,
    render_cockpit,
    render_context,
    render_dirs,
    render_dossier_index,
)
from basecamp.mcp.resolve import resolve_project
from basecamp.mcp.tools.workstreams import create_workstream as run_create_workstream
from mcp.server.fastmcp import FastMCP

_SERVER_NAME = "basecamp"


def build_server(cwd: str | None = None) -> FastMCP:
    """Build the FastMCP server, resolving awareness from ``cwd`` (default: getcwd)."""
    working_dir = cwd or os.getcwd()
    startup = resolve_project(working_dir)
    mcp = FastMCP(_SERVER_NAME, instructions=build_instructions(startup))

    @mcp.resource(
        "basecamp://project/dirs",
        name="Related directories",
        description="Related working directories configured for this project.",
        mime_type="text/markdown",
    )
    def project_dirs() -> str:
        return render_dirs(resolve_project(working_dir))

    @mcp.resource(
        "basecamp://project/context",
        name="Project context",
        description="Curated standing context and conventions for this project.",
        mime_type="text/markdown",
    )
    def project_context() -> str:
        return render_context(resolve_project(working_dir))

    @mcp.resource(
        "basecamp://logseq/cockpit",
        name="Repo cockpit",
        description="The repo's coordination cockpit page from the shared Logseq graph.",
        mime_type="text/markdown",
    )
    def logseq_cockpit() -> str:
        return render_cockpit(resolve_logseq(working_dir))

    @mcp.resource(
        "basecamp://logseq/dossiers",
        name="Work dossiers",
        description="A pointer index of the repo's work dossiers in the shared Logseq graph.",
        mime_type="text/markdown",
    )
    def logseq_dossiers() -> str:
        return render_dossier_index(resolve_logseq(working_dir))

    @mcp.tool()
    def create_workstream(label: str, dossier_path: str | None = None) -> dict[str, Any]:
        """Stage a workstream: create its record, a permanent worktree, and a Herdr pane.

        Use when the user has shaped a piece of work and wants it staged for
        execution. ``label`` is a short human title (e.g. "auth refactor").
        ``dossier_path`` points at the shared-Logseq work page holding the brief.
        Returns the minted slug/id, the worktree, and the pane status; a failed pane
        still yields a valid record + worktree with a manual next step.
        """

        return run_create_workstream(label=label, dossier_path=dossier_path, cwd=working_dir)

    return mcp


def main() -> None:
    """Console-script entry point (``basecamp-mcp``): run the stdio server."""
    build_server().run()


if __name__ == "__main__":
    main()
