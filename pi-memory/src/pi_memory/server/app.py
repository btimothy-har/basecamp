"""FastAPI application factory for pi-memory."""

import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI

from pi_memory.constants import DEFAULT_HOST, DEFAULT_PORT, MEMORY_DIR, SERVICE_NAME, SERVICE_VERSION


def create_app(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    memory_dir: Path = MEMORY_DIR,
    started_at: datetime | None = None,
) -> FastAPI:
    """Create the local Pi memory FastAPI application."""
    service_started_at = datetime.now(UTC) if started_at is None else started_at
    service_memory_dir = memory_dir.expanduser()

    app = FastAPI(title=SERVICE_NAME, version=SERVICE_VERSION)
    app.state.started_at = service_started_at
    app.state.host = host
    app.state.port = port
    app.state.memory_dir = service_memory_dir

    @app.get("/health")
    def health() -> dict[str, str]:
        """Return a lightweight health check response."""
        return {"status": "ok"}

    @app.get("/v1/status")
    def status() -> dict[str, object]:
        """Return process and service status metadata."""
        now = datetime.now(UTC)
        uptime_seconds = max(0.0, (now - app.state.started_at).total_seconds())
        return {
            "service_name": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "pid": os.getpid(),
            "started_at": app.state.started_at.isoformat(),
            "uptime_seconds": uptime_seconds,
            "host": app.state.host,
            "port": app.state.port,
            "memory_dir": str(app.state.memory_dir),
        }

    return app
