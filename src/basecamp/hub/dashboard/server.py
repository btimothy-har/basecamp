"""Managed secondary Uvicorn listener for the localhost dashboard."""

from __future__ import annotations

import errno
import socket
import threading
from collections.abc import Callable

import uvicorn
from fastapi import FastAPI

from .access import DashboardAccess
from .app import DASHBOARD_HOST, DASHBOARD_PORT, create_dashboard_app

DASHBOARD_START_TIMEOUT_SECONDS = 3.0
DASHBOARD_STOP_TIMEOUT_SECONDS = 3.0


class _DashboardUvicornServer(uvicorn.Server):
    def __init__(
        self,
        config: uvicorn.Config,
        *,
        access: DashboardAccess,
        origin: str,
        ready: threading.Event,
    ) -> None:
        super().__init__(config)
        self._access = access
        self._origin = origin
        self._ready = ready

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.started:
            self._access.set_available(self._origin)
        self._ready.set()


class DashboardServer:
    """Pre-bound TCP listener whose failure never owns hub process lifetime."""

    def __init__(
        self,
        *,
        access: DashboardAccess,
        uds_path: str,
        host: str = DASHBOARD_HOST,
        port: int = DASHBOARD_PORT,
        app_factory: Callable[..., FastAPI] = create_dashboard_app,
    ) -> None:
        self.access = access
        self.uds_path = uds_path
        self.host = host
        self.port = port
        self._app_factory = app_factory
        self._listener: socket.socket | None = None
        self._server: _DashboardUvicornServer | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._failure: str | None = None

    @property
    def server(self) -> uvicorn.Server | None:
        return self._server

    @property
    def thread(self) -> threading.Thread | None:
        return self._thread

    def start(self, *, timeout: float = DASHBOARD_START_TIMEOUT_SECONDS) -> bool:
        if self._thread is not None:
            return self.access.availability().available

        try:
            listener = self._bind_listener()
            actual_port = int(listener.getsockname()[1])
            expected_host = f"{self.host}:{actual_port}"
            origin = f"http://{expected_host}"
            app = self._app_factory(
                access=self.access,
                uds_path=self.uds_path,
                expected_host=expected_host,
                expected_origin=origin,
            )
            config = uvicorn.Config(
                app,
                host=self.host,
                port=actual_port,
                access_log=False,
                server_header=False,
                date_header=False,
                log_level="warning",
            )
            self.port = actual_port
            self._server = _DashboardUvicornServer(config, access=self.access, origin=origin, ready=self._ready)
            self._thread = threading.Thread(
                target=self._run,
                args=(self._server, listener),
                name="basecamp-dashboard",
                daemon=True,
            )
            self._thread.start()
        except Exception as error:  # noqa: BLE001
            self._thread = None
            self._server = None
            self._close_listener()
            self.access.set_unavailable(self._startup_failure(error))
            return False
        ready = self._ready.wait(timeout)
        availability = self.access.availability()
        if not ready or not availability.available:
            reason = self._failure or availability.reason or self._startup_failure(RuntimeError())
            self.stop(timeout=timeout)
            self.access.set_unavailable(reason)
            return False
        return True

    def stop(self, *, timeout: float = DASHBOARD_STOP_TIMEOUT_SECONDS) -> bool:
        self.access.set_unavailable("dashboard listener is stopped")
        server = self._server
        thread = self._thread
        if server is not None:
            server.should_exit = True
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        if thread is not None and thread.is_alive():
            # A stuck secondary listener must never keep the UDS hub shutdown waiting.
            if server is not None:
                server.force_exit = True
            self._close_listener()
            return False
        self._close_listener()
        return True

    def _bind_listener(self) -> socket.socket:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener = listener
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        if hasattr(socket, "SO_REUSEPORT"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 0)
        listener.bind((self.host, self.port))
        listener.listen(socket.SOMAXCONN)
        return listener

    def _run(self, server: _DashboardUvicornServer, listener: socket.socket) -> None:
        try:
            server.run(sockets=[listener])
        except Exception as error:  # noqa: BLE001
            self._failure = self._startup_failure(error)
        finally:
            self.access.set_unavailable(self._failure or "dashboard listener is stopped")
            self._ready.set()
            self._close_listener()

    def _close_listener(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is None:
            return
        try:
            listener.close()
        except OSError:
            pass

    def _startup_failure(self, error: BaseException) -> str:
        if isinstance(error, OSError) and error.errno == errno.EADDRINUSE:
            return f"dashboard port {self.host}:{self.port} is already in use"
        return f"dashboard listener failed to start on {self.host}:{self.port}"
