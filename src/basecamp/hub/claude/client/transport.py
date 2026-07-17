"""HTTP-over-Unix-domain-socket transport for the ensure-daemon client.

Mirrors the retired TypeScript connector's ``http.ts``: a GET ``/health`` probe
that treats any non-200 / malformed / timed-out response as "not healthy", plus
a small JSON POST used by the session-lifecycle RPCs. All failures are swallowed
into a falsy result — callers decide what to do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

#: Per-probe health timeout (matches the connector's 400 ms default).
DEFAULT_HEALTH_TIMEOUT_S = 0.4
#: Timeout for session-lifecycle POSTs.
DEFAULT_POST_TIMEOUT_S = 2.0


@dataclass(frozen=True)
class HealthResult:
    """Outcome of a ``/health`` probe."""

    ok: bool
    protocol: int | None = None


def _client(socket_path: str, timeout: float) -> httpx.Client:
    transport = httpx.HTTPTransport(uds=socket_path)
    return httpx.Client(transport=transport, base_url="http://daemon", timeout=timeout)


def health_ping(socket_path: str, timeout: float = DEFAULT_HEALTH_TIMEOUT_S) -> HealthResult:
    """Probe ``GET /health``; healthy iff HTTP 200 + ``{status:"ok", protocol:int}``."""

    try:
        with _client(socket_path, timeout) as client:
            response = client.get("/health")
    except (httpx.HTTPError, OSError):
        return HealthResult(ok=False)

    if response.status_code != 200:
        return HealthResult(ok=False)
    try:
        body = response.json()
    except ValueError:
        return HealthResult(ok=False)

    if not isinstance(body, dict) or body.get("status") != "ok":
        return HealthResult(ok=False)
    protocol = body.get("protocol")
    if isinstance(protocol, int) and not isinstance(protocol, bool):
        return HealthResult(ok=True, protocol=protocol)
    return HealthResult(ok=False)


def post_json(
    socket_path: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_POST_TIMEOUT_S,
) -> tuple[int, Any]:
    """POST JSON over the UDS; return ``(status_code, parsed_body_or_None)``."""

    with _client(socket_path, timeout) as client:
        response = client.post(path, json=body if body is not None else {})
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, None


def get_json(
    socket_path: str,
    path: str,
    params: dict[str, Any] | None = None,
    timeout: float = DEFAULT_POST_TIMEOUT_S,
) -> tuple[int, Any]:
    """GET JSON over the UDS; return ``(status_code, parsed_body_or_None)``."""

    with _client(socket_path, timeout) as client:
        response = client.get(path, params=params or None)
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, None


def delete_json(
    socket_path: str,
    path: str,
    timeout: float = DEFAULT_POST_TIMEOUT_S,
) -> tuple[int, Any]:
    """DELETE over the UDS; return ``(status_code, parsed_body_or_None)``."""

    with _client(socket_path, timeout) as client:
        response = client.delete(path)
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, None
