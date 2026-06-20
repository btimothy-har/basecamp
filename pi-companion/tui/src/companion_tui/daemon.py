"""Unix-socket HTTP client for polling daemon run summaries."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

DEFAULT_DAEMON_SOCKET_PATH = Path("~/.pi/basecamp/swarm/daemon.sock").expanduser()
DEFAULT_DAEMON_SUMMARY_LIMIT = 5
DEFAULT_DAEMON_TIMEOUT_SECONDS = 0.5

DaemonSummaryState = Literal["ok", "unavailable", "error"]


@dataclass(frozen=True)
class DaemonSummaryCounts:
    """Aggregate run counts from the daemon summary endpoint."""

    pending: int
    running: int
    completed: int
    failed: int
    total: int


@dataclass(frozen=True)
class DaemonSummaryRun:
    """One previewed run in a daemon summary payload."""

    run_id: str
    agent_id: str
    parent_id: str | None
    role: str
    session_name: str
    status: str
    result_preview: str | None
    error_preview: str | None
    exit_code: int | None
    created_at: str | None
    started_at: str | None
    ended_at: str | None


@dataclass(frozen=True)
class DaemonSummaryUnavailable:
    """Returned when the daemon socket/connection cannot be reached."""

    state: Literal["unavailable"] = "unavailable"
    error: str = ""


@dataclass(frozen=True)
class DaemonSummaryError:
    """Returned when daemon response is malformed or not successful."""

    state: Literal["error"] = "error"
    error: str = ""


@dataclass(frozen=True)
class DaemonSummaryOk:
    """Returned on a valid daemon summary response."""

    root_id: str
    counts: DaemonSummaryCounts
    runs: list[DaemonSummaryRun]
    session_active: bool
    state: Literal["ok"] = "ok"


DaemonSummary = DaemonSummaryOk | DaemonSummaryUnavailable | DaemonSummaryError


class UnixHTTPConnection(HTTPConnection):
    """HTTPConnection that connects over an AF_UNIX socket."""

    def __init__(self, uds_path: str, *, timeout: float = DEFAULT_DAEMON_TIMEOUT_SECONDS) -> None:
        super().__init__("localhost", 80, timeout=timeout)
        self._uds_path = uds_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self._uds_path)
        except OSError:
            sock.close()
            raise
        self.sock = sock


class DaemonSummarySource:
    """Polls the daemon `/runs/summary` endpoint."""

    def __init__(
        self,
        daemon_socket: str | Path | None = None,
        *,
        connection_factory: type[HTTPConnection] = UnixHTTPConnection,
        default_limit: int = DEFAULT_DAEMON_SUMMARY_LIMIT,
        timeout: float = DEFAULT_DAEMON_TIMEOUT_SECONDS,
    ) -> None:
        socket_path = daemon_socket if daemon_socket is not None else DEFAULT_DAEMON_SOCKET_PATH
        self._daemon_socket = str(socket_path.expanduser() if isinstance(socket_path, Path) else socket_path)
        self._connection_factory = connection_factory
        self._default_limit = default_limit
        self._timeout = timeout

    def poll(self, root_id: str, *, limit: int | None = None) -> DaemonSummary:
        """Fetch a daemon summary for the given root ID.

        Returns:
            DaemonSummaryOk: parsed payload.
            DaemonSummaryUnavailable: socket/connection could not be opened.
            DaemonSummaryError: non-200 response or malformed payload.
        """

        if not isinstance(root_id, str):
            return DaemonSummaryError(error="root_id must be a string")

        poll_limit = self._default_limit if limit is None else limit
        if not isinstance(poll_limit, int):
            return DaemonSummaryError(error="limit must be an int")

        request_path = f"/runs/summary?{urlencode({'root_id': root_id, 'limit': poll_limit})}"
        connection: HTTPConnection | None = None

        try:
            connection = self._connection_factory(self._daemon_socket, timeout=self._timeout)
            connection.request("GET", request_path, headers={"Accept": "application/json"})
            response = connection.getresponse()

            if response.status != 200:
                return DaemonSummaryError(error=f"daemon returned status {response.status}")

            payload = json.loads(response.read().decode("utf-8"))
            return _parse_payload(payload)
        except OSError as error:
            return DaemonSummaryUnavailable(error=str(error))
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
            return DaemonSummaryError(error="daemon returned an invalid summary response")
        except HTTPException as error:
            return DaemonSummaryError(error=str(error))
        finally:
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass


def _expect_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError
    return value


def _expect_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise TypeError
    return value


def _expect_optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError
    return value


def _expect_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise TypeError
    return value


def _expect_optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError
    return value


def _parse_payload(payload: object) -> DaemonSummaryOk:
    if not isinstance(payload, dict):
        raise TypeError

    counts_payload = payload.get("counts")
    if not isinstance(counts_payload, dict):
        raise TypeError

    runs_payload = payload.get("runs")
    if not isinstance(runs_payload, list):
        raise TypeError

    counts = DaemonSummaryCounts(
        pending=_expect_int(counts_payload, "pending"),
        running=_expect_int(counts_payload, "running"),
        completed=_expect_int(counts_payload, "completed"),
        failed=_expect_int(counts_payload, "failed"),
        total=_expect_int(counts_payload, "total"),
    )

    runs = [
        DaemonSummaryRun(
            run_id=_expect_str(raw_run, "run_id"),
            agent_id=_expect_str(raw_run, "agent_id"),
            parent_id=_expect_optional_str(raw_run, "parent_id"),
            role=_expect_str(raw_run, "role"),
            session_name=_expect_str(raw_run, "session_name"),
            status=_expect_str(raw_run, "status"),
            result_preview=_expect_optional_str(raw_run, "result_preview"),
            error_preview=_expect_optional_str(raw_run, "error_preview"),
            exit_code=_expect_optional_int(raw_run, "exit_code"),
            created_at=_expect_optional_str(raw_run, "created_at"),
            started_at=_expect_optional_str(raw_run, "started_at"),
            ended_at=_expect_optional_str(raw_run, "ended_at"),
        )
        for raw_run in runs_payload
        if isinstance(raw_run, dict)
    ]

    if len(runs) != len(runs_payload):
        raise TypeError

    return DaemonSummaryOk(
        root_id=_expect_str(payload, "root_id"),
        counts=counts,
        runs=runs,
        session_active=_expect_bool(payload, "session_active"),
    )


__all__ = [
    "DEFAULT_DAEMON_SOCKET_PATH",
    "DEFAULT_DAEMON_SUMMARY_LIMIT",
    "DEFAULT_DAEMON_TIMEOUT_SECONDS",
    "DaemonSummary",
    "DaemonSummaryState",
    "DaemonSummaryCounts",
    "DaemonSummaryError",
    "DaemonSummaryOk",
    "DaemonSummaryRun",
    "DaemonSummarySource",
    "DaemonSummaryUnavailable",
    "UnixHTTPConnection",
]
