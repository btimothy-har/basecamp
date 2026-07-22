"""Allowlisted dashboard HTTP client over the private daemon UDS."""

from __future__ import annotations

import json
import socket
from http.client import HTTPConnection, HTTPException
from typing import Any, Protocol
from urllib.parse import urlencode

DASHBOARD_UDS_TIMEOUT_SECONDS = 1.0
DASHBOARD_UDS_RESPONSE_MAX_BYTES = 8 * 1024 * 1024


class DashboardUdsError(RuntimeError):
    """Private dashboard endpoint or transport failed."""

    def __init__(self, detail: str, *, status: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status

    @classmethod
    def invalid_bootstrap(cls) -> DashboardUdsError:
        return cls("daemon returned an invalid dashboard bootstrap response")

    @classmethod
    def response_too_large(cls, status: int) -> DashboardUdsError:
        return cls("daemon dashboard response exceeded the size limit", status=status)

    @classmethod
    def response_status(cls, status: int, detail: Any) -> DashboardUdsError:
        message = detail if isinstance(detail, str) else f"daemon returned status {status}"
        return cls(message[:240], status=status)

    @classmethod
    def unavailable(cls) -> DashboardUdsError:
        return cls("daemon dashboard endpoint is unavailable")

    @classmethod
    def invalid_json(cls) -> DashboardUdsError:
        return cls("daemon returned invalid dashboard JSON")

    @classmethod
    def invalid_payload(cls) -> DashboardUdsError:
        return cls("daemon returned an invalid dashboard payload")


class DashboardDataSource(Protocol):
    """Only UDS reads the TCP dashboard app is allowed to perform."""

    def get_snapshot(self) -> dict[str, Any]: ...

    def get_messages(self, *, root_handle: str, agent_handle: str) -> dict[str, Any]: ...


class UnixSocketHTTPConnection(HTTPConnection):
    """HTTP connection transported over one Unix-domain socket."""

    def __init__(self, uds_path: str, *, timeout: float) -> None:
        super().__init__("localhost", 80, timeout=timeout)
        self._uds_path = uds_path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        try:
            connection.connect(self._uds_path)
        except OSError:
            connection.close()
            raise
        self.sock = connection


class DashboardUdsClient:
    """Fixed-method client for the daemon's private dashboard endpoints."""

    def __init__(
        self,
        uds_path: str,
        *,
        connection_factory: type[HTTPConnection] = UnixSocketHTTPConnection,
        timeout: float = DASHBOARD_UDS_TIMEOUT_SECONDS,
    ) -> None:
        self._uds_path = uds_path
        self._connection_factory = connection_factory
        self._timeout = timeout

    def get_snapshot(self) -> dict[str, Any]:
        return self._request_json("GET", "/dashboard/snapshot")

    def get_messages(self, *, root_handle: str, agent_handle: str) -> dict[str, Any]:
        query = urlencode({"root_handle": root_handle, "agent_handle": agent_handle})
        return self._request_json("GET", f"/dashboard/messages?{query}")

    def mint_bootstrap_url(self) -> str:
        payload = self._request_json("POST", "/dashboard/bootstrap")
        url = payload.get("url")
        if not isinstance(url, str) or not url:
            raise DashboardUdsError.invalid_bootstrap()
        return url

    def _request_json(self, method: str, path: str) -> dict[str, Any]:
        connection = self._connection_factory(self._uds_path, timeout=self._timeout)
        try:
            connection.request(
                method,
                path,
                body=b"" if method == "POST" else None,
                headers={"Accept": "application/json"},
            )
            response = connection.getresponse()
            body = response.read(DASHBOARD_UDS_RESPONSE_MAX_BYTES + 1)
            if len(body) > DASHBOARD_UDS_RESPONSE_MAX_BYTES:
                raise DashboardUdsError.response_too_large(response.status)
            payload = self._decode_payload(body)
            if response.status == 200:
                return payload
            raise DashboardUdsError.response_status(response.status, payload.get("detail"))
        except (OSError, HTTPException) as error:
            raise DashboardUdsError.unavailable() from error
        finally:
            try:
                connection.close()
            except OSError:
                pass

    @staticmethod
    def _decode_payload(body: bytes) -> dict[str, Any]:
        try:
            payload: Any = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise DashboardUdsError.invalid_json() from error
        if not isinstance(payload, dict):
            raise DashboardUdsError.invalid_payload()
        return payload
