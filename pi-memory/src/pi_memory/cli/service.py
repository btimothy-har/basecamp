"""CLI service status and startup helpers."""

from __future__ import annotations

import errno
import importlib
import ipaddress
import json
import socket
import urllib.error
import urllib.request
from typing import Any

import click

from pi_memory.constants import SERVICE_NAME

DEFAULT_STATUS_TIMEOUT_SECONDS = 1.0


class PortBindError(click.ClickException):
    """Raised when the local service cannot bind its requested port."""

    def __init__(self, *, host: str, port: int, reason: str) -> None:
        super().__init__(f"{SERVICE_NAME} cannot start at {_service_base_url(host=host, port=port)}: {reason}")

    @classmethod
    def in_use(cls, *, host: str, port: int) -> PortBindError:
        """Return an error for a port already bound by another process."""
        return cls(host=host, port=port, reason="the port is already in use by another process")


class StatusProbeError(Exception):
    """Raised when the local service status probe fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message)

    @classmethod
    def http_status(cls, code: int) -> StatusProbeError:
        """Return an error for an unexpected HTTP response."""
        return cls(f"HTTP {code} from status endpoint")

    @classmethod
    def unavailable(cls, reason: str) -> StatusProbeError:
        """Return an error for an unavailable service."""
        return cls(reason)

    @classmethod
    def timed_out(cls) -> StatusProbeError:
        """Return an error for a timed out status probe."""
        return cls("timed out waiting for status endpoint")

    @classmethod
    def invalid_json(cls) -> StatusProbeError:
        """Return an error for an invalid JSON response."""
        return cls("status endpoint returned invalid JSON")

    @classmethod
    def unexpected_json(cls) -> StatusProbeError:
        """Return an error for an unexpected JSON response shape."""
        return cls("status endpoint returned unexpected JSON")


def _ensure_port_available(*, host: str, port: int) -> None:
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise PortBindError(host=host, port=port, reason=str(error)) from error

    errors: list[OSError] = []
    seen: set[tuple[int, int, int, Any]] = set()
    for family, socktype, proto, _canonname, sockaddr in addresses:
        key = (family, socktype, proto, sockaddr)
        if key in seen:
            continue
        seen.add(key)
        try:
            with socket.socket(family, socktype, proto) as sock:
                sock.bind(sockaddr)
        except OSError as error:
            if error.errno == errno.EADDRINUSE:
                raise PortBindError.in_use(host=host, port=port) from error
            errors.append(error)

    if not seen:
        raise PortBindError(host=host, port=port, reason="host did not resolve to a bind address")
    if errors and len(errors) == len(seen):
        raise PortBindError(host=host, port=port, reason=str(errors[0])) from errors[0]


def _status_url(*, host: str, port: int) -> str:
    return f"{_service_base_url(host=host, port=port)}/v1/status"


def _service_base_url(*, host: str, port: int) -> str:
    return f"http://{_http_host(host)}:{port}"


def _http_host(host: str) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host

    if address.version == 6:
        return f"[{host}]"
    return host


def _fetch_status(*, url: str, timeout: float) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    auth_header = _status_auth_header()
    if auth_header is not None:
        headers["Authorization"] = auth_header
    request = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raise StatusProbeError.http_status(error.code) from error
    except urllib.error.URLError as error:
        raise StatusProbeError.unavailable(_url_error_reason(error)) from error
    except TimeoutError as error:
        raise StatusProbeError.timed_out() from error
    except OSError as error:
        raise StatusProbeError.unavailable(str(error)) from error

    try:
        data = json.loads(content)
    except json.JSONDecodeError as error:
        raise StatusProbeError.invalid_json() from error

    if not isinstance(data, dict):
        raise StatusProbeError.unexpected_json()
    return data


def _status_auth_header() -> str | None:
    # Avoid importing server.app while the CLI module graph is still loading.
    state_module = importlib.import_module("pi_memory.server.state")
    metadata = state_module.ServerState().read_metadata()
    if metadata is None:
        return None
    auth_token = metadata.get("auth_token")
    if not isinstance(auth_token, str) or not auth_token:
        return None
    return f"Bearer {auth_token}"


def _url_error_reason(error: urllib.error.URLError) -> str:
    reason = error.reason
    if isinstance(reason, TimeoutError):
        return "timed out waiting for status endpoint"
    return str(reason)
