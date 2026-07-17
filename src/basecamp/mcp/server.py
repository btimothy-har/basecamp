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

from basecamp.claude.memory import resolve_memory
from basecamp.mcp.render import (
    build_instructions,
    render_cockpit,
    render_context,
    render_dirs,
    render_dossier_index,
)
from basecamp.mcp.resolve import resolve_project
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
        "basecamp://memory/cockpit",
        name="Repo cockpit",
        description="The repo's durable coordination cockpit page from shared Logseq memory.",
        mime_type="text/markdown",
    )
    def memory_cockpit() -> str:
        return render_cockpit(resolve_memory(working_dir))

    @mcp.resource(
        "basecamp://memory/dossiers",
        name="Work dossiers",
        description="A pointer index of the repo's work dossiers in shared Logseq memory.",
        mime_type="text/markdown",
    )
    def memory_dossiers() -> str:
        return render_dossier_index(resolve_memory(working_dir))

    return mcp


def main() -> None:
    """Console-script entry point (``basecamp-mcp``): run the stdio server."""
    build_server().run()


if __name__ == "__main__":
    main()
