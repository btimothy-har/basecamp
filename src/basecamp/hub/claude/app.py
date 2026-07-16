"""FastAPI application for the Claude Code session-lifecycle hub daemon.

Deliberately tiny: health plus the hook-driven session routes over a single
:class:`SessionStore`. None of the Pi swarm coordination surface (WebSocket,
dispatch, workstreams, analysis) is wired here — importing ``basecamp.hub.app``
would drag the whole swarm service graph along with it, which is exactly what the
promotable Claude section must not depend on.
"""

from __future__ import annotations

from fastapi import FastAPI

from .routes import register_claude_routes
from .store import SessionStore


def create_claude_app(store: SessionStore) -> FastAPI:
    """Create the Claude hub daemon's FastAPI app over ``store``."""

    app = FastAPI()
    register_claude_routes(app, store=store)
    return app
