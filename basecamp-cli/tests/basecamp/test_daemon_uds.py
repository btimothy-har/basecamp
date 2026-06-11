"""UDS integration test for daemon health route."""

from __future__ import annotations

import os
import stat
import threading
import time
import uuid
from pathlib import Path

import httpx
import uvicorn
from basecamp.daemon.app import create_app
from basecamp.daemon.server import UdsServer
from basecamp.daemon.store import Store


class _ThreadedServer(UdsServer):
    def install_signal_handlers(self) -> None:  # noqa: D401
        """Disable signal handlers when running under a background thread."""


def test_health_over_real_uds(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    if uds_path.exists():
        uds_path.unlink()

    app = create_app(Store(db_path=db_path))

    config = uvicorn.Config(app=app, uds=str(uds_path), log_level="error")
    server = _ThreadedServer(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while time.time() < deadline and not uds_path.exists():
        time.sleep(0.05)

    transport = httpx.HTTPTransport(uds=str(uds_path))
    try:
        deadline = time.time() + 5
        response = None
        while time.time() < deadline:
            try:
                with httpx.Client(transport=transport, base_url="http://daemon") as client:
                    response = client.get("/health")
                break
            except (httpx.ConnectError, FileNotFoundError):
                time.sleep(0.05)

        assert response is not None
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "protocol": 2}

        socket_mode = stat.S_IMODE(uds_path.stat().st_mode)
        assert socket_mode == 0o600, f"socket perms {socket_mode:o} should be 0600 (local-user only)"
    finally:
        transport.close()
        server.should_exit = True
        thread.join(timeout=5)
        if uds_path.exists():
            uds_path.unlink()
