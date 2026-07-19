"""FastAPI application for the Claude Code session-lifecycle hub daemon.

Deliberately tiny: health plus the hook-driven session routes over a single
:class:`SessionStore`.

The one non-route concern is shutdown: transcript ingest runs as a detached
background task (see :class:`.ingest.IngestScheduler`), so a ``lifespan`` handler
drains it before the process exits — otherwise a shutdown mid-parse (notably the
protocol-bump respawn that SIGTERMs a running daemon) could silently drop the
"last-chance" SessionEnd ingest.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI

from .routes import register_claude_routes
from .store import SessionStore

logger = logging.getLogger(__name__)

#: Bounded window to finish in-flight transcript ingests on shutdown. Kept below
#: the ensure-daemon client's SIGTERM→SIGKILL window
#: (:data:`.client.process.DEFAULT_STOP_TIMEOUT_S`) so a graceful drain completes
#: before the client escalates to SIGKILL.
_DRAIN_TIMEOUT_S = 3.0


def create_claude_app(store: SessionStore) -> FastAPI:
    """Create the Claude hub daemon's FastAPI app over ``store``."""

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        # SessionEnd is the "last-chance" transcript capture, but the parse runs as
        # a detached background task; drain it before exit so a shutdown mid-parse
        # doesn't silently drop it. Bounded so a hung parse can't block shutdown.
        scheduler = getattr(app.state, "ingest_scheduler", None)
        if scheduler is None:
            return
        try:
            await asyncio.wait_for(scheduler.drain(), timeout=_DRAIN_TIMEOUT_S)
        except TimeoutError:
            logger.warning("transcript ingest drain timed out after %.1fs on shutdown", _DRAIN_TIMEOUT_S)

    app = FastAPI(lifespan=lifespan)
    register_claude_routes(app, store=store)
    return app
