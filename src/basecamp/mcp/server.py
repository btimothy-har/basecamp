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

from basecamp.mcp.render import build_instructions, render_context, render_dirs
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

    return mcp


def main() -> None:
    """Console-script entry point (``basecamp-mcp``): run the stdio server."""
    build_server().run()


if __name__ == "__main__":
    main()
