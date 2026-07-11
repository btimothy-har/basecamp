"""Unix-socket HTTP client for polling daemon run summaries."""

from __future__ import annotations

import json
import socket
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from urllib.parse import quote, urlencode

from basecamp.companion.analysis import CompanionAnalysis
from basecamp.companion.daemon.models import (
    DaemonAgentMessage,
    DaemonAgentMessages,
    DaemonAgentMessagesError,
    DaemonAgentMessagesOk,
    DaemonAgentMessagesState,
    DaemonAgentMessagesUnavailable,
    DaemonCurrentTask,
    DaemonRecentActivity,
    DaemonSkillInvocation,
    DaemonSummary,
    DaemonSummaryAgent,
    DaemonSummaryCounts,
    DaemonSummaryError,
    DaemonSummaryOk,
    DaemonSummaryState,
    DaemonSummaryUnavailable,
    DaemonTaskPlanItem,
    DaemonTaskProgress,
    DaemonTaskProjection,
)
from basecamp.companion.daemon.parse import _parse_messages_payload, _parse_payload

DEFAULT_DAEMON_SOCKET_PATH = Path("~/.pi/basecamp/swarm/daemon.sock").expanduser()
DEFAULT_DAEMON_MESSAGES_LIMIT = 3
DEFAULT_DAEMON_SUMMARY_LIMIT = 5
DEFAULT_DAEMON_TIMEOUT_SECONDS = 0.5


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
    """Polls daemon Swarm observability endpoints."""

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
        """Fetch a daemon summary for the given root ID."""

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

    def poll_analysis(self, session_id: str) -> CompanionAnalysis | None:
        """Fetch the daemon's stored analysis for a session; None if absent/unreachable.

        Best-effort: any non-200 (e.g. 404 when no analysis exists yet), a daemon-down
        socket error, or an invalid body yields ``None`` and the dashboard shows "—".
        """

        if not isinstance(session_id, str):
            return None

        request_path = f"/analysis/{quote(session_id, safe='')}"
        connection: HTTPConnection | None = None
        try:
            connection = self._connection_factory(self._daemon_socket, timeout=self._timeout)
            connection.request("GET", request_path, headers={"Accept": "application/json"})
            response = connection.getresponse()
            body = response.read()
            if response.status != 200:
                return None
            return CompanionAnalysis.model_validate(json.loads(body.decode("utf-8")))
        except (OSError, HTTPException, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
            return None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass

    def poll_messages(
        self,
        root_id: str,
        agent_handle: str,
        *,
        limit: int | None = None,
    ) -> DaemonAgentMessages:
        """Fetch message detail for one selected agent."""

        if not isinstance(root_id, str):
            return DaemonAgentMessagesError(error="root_id must be a string")
        if not isinstance(agent_handle, str):
            return DaemonAgentMessagesError(error="agent_handle must be a string")

        poll_limit = DEFAULT_DAEMON_MESSAGES_LIMIT if limit is None else limit
        if not isinstance(poll_limit, int):
            return DaemonAgentMessagesError(error="limit must be an int")

        query = urlencode({"root_id": root_id, "agent_handle": agent_handle, "limit": poll_limit})
        request_path = f"/runs/messages?{query}"
        connection: HTTPConnection | None = None

        try:
            connection = self._connection_factory(self._daemon_socket, timeout=self._timeout)
            connection.request("GET", request_path, headers={"Accept": "application/json"})
            response = connection.getresponse()

            if response.status != 200:
                return DaemonAgentMessagesError(error=f"daemon returned status {response.status}")

            payload = json.loads(response.read().decode("utf-8"))
            return _parse_messages_payload(payload)
        except OSError as error:
            return DaemonAgentMessagesUnavailable(error=str(error))
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
            return DaemonAgentMessagesError(error="daemon returned an invalid messages response")
        except HTTPException as error:
            return DaemonAgentMessagesError(error=str(error))
        finally:
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass


__all__ = [
    "DEFAULT_DAEMON_MESSAGES_LIMIT",
    "DEFAULT_DAEMON_SOCKET_PATH",
    "DEFAULT_DAEMON_SUMMARY_LIMIT",
    "DEFAULT_DAEMON_TIMEOUT_SECONDS",
    "DaemonAgentMessage",
    "DaemonAgentMessages",
    "DaemonAgentMessagesError",
    "DaemonAgentMessagesOk",
    "DaemonAgentMessagesState",
    "DaemonAgentMessagesUnavailable",
    "DaemonSummary",
    "DaemonSkillInvocation",
    "DaemonSummaryState",
    "DaemonSummaryCounts",
    "DaemonSummaryError",
    "DaemonSummaryOk",
    "DaemonCurrentTask",
    "DaemonRecentActivity",
    "DaemonSummaryAgent",
    "DaemonSummarySource",
    "DaemonSummaryUnavailable",
    "DaemonTaskPlanItem",
    "DaemonTaskProgress",
    "DaemonTaskProjection",
    "UnixHTTPConnection",
]
