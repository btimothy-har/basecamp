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
DEFAULT_DAEMON_MESSAGES_LIMIT = 3
DEFAULT_DAEMON_SUMMARY_LIMIT = 5
DEFAULT_DAEMON_TIMEOUT_SECONDS = 0.5

DaemonAgentMessagesState = Literal["ok", "unavailable", "error"]
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
class DaemonTaskProgress:
    """Task progress counts from a daemon task projection."""

    completed: int
    deleted: int
    total: int


@dataclass(frozen=True)
class DaemonTaskPlanItem:
    """One task-plan item from a daemon task projection."""

    index: int
    label: str
    status: str


@dataclass(frozen=True)
class DaemonCurrentTask:
    """Current task detail from a daemon task projection."""

    index: int
    label: str
    status: str
    description: str | None
    notes: str | None


@dataclass(frozen=True)
class DaemonTaskProjection:
    """Safe daemon task projection for companion display."""

    goal: str | None
    progress: DaemonTaskProgress | None
    task_plan: list[DaemonTaskPlanItem]
    current_task: DaemonCurrentTask | None


@dataclass(frozen=True)
class DaemonRecentActivity:
    """Allowlisted recent activity fields from a daemon projection."""

    kind: str
    seq: int | None
    timestamp: str | None
    tool_name: str | None
    turn_index: int | None
    category: str | None = None
    label: str | None = None
    snippet: str | None = None
    is_error: bool | None = None
    tool_count: int | None = None


@dataclass(frozen=True)
class DaemonAgentMessage:
    """One selected-agent assistant message from the daemon."""

    kind: str
    seq: int | None
    timestamp: str | None
    label: str | None
    text: str


@dataclass(frozen=True)
class DaemonAgentMessagesUnavailable:
    """Returned when daemon message detail cannot be reached."""

    state: Literal["unavailable"] = "unavailable"
    error: str = ""


@dataclass(frozen=True)
class DaemonAgentMessagesError:
    """Returned when daemon message detail is malformed or unsuccessful."""

    state: Literal["error"] = "error"
    error: str = ""


@dataclass(frozen=True)
class DaemonAgentMessagesOk:
    """Message detail for one selected agent."""

    root_id: str
    agent_handle: str
    messages: list[DaemonAgentMessage]
    state: Literal["ok"] = "ok"


DaemonAgentMessages = DaemonAgentMessagesOk | DaemonAgentMessagesUnavailable | DaemonAgentMessagesError


@dataclass(frozen=True)
class DaemonSummaryAgent:
    """One previewed agent in a daemon summary payload."""

    agent_handle: str
    agent_type: str | None
    role: str
    session_name: str
    status: str
    result_preview: str | None
    error_preview: str | None
    exit_code: int | None
    created_at: str | None
    started_at: str | None
    ended_at: str | None
    agent_id_short: str | None = None
    model: str | None = None
    task: DaemonTaskProjection | None = None
    recent_activity: list[DaemonRecentActivity] | None = None


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
    agents: list[DaemonSummaryAgent]
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


def _activity_optional_bool(payload: dict[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    return value if isinstance(value, bool) else None


def _activity_optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _activity_optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _expect_optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError
    return value


def _parse_task_progress(payload: object) -> DaemonTaskProgress | None:
    if not isinstance(payload, dict):
        return None

    try:
        return DaemonTaskProgress(
            completed=_expect_int(payload, "completed"),
            deleted=_expect_int(payload, "deleted"),
            total=_expect_int(payload, "total"),
        )
    except TypeError:
        return None


def _parse_task_plan_item(payload: object) -> DaemonTaskPlanItem | None:
    if not isinstance(payload, dict):
        return None

    try:
        return DaemonTaskPlanItem(
            index=_expect_int(payload, "index"),
            label=_expect_str(payload, "label"),
            status=_expect_str(payload, "status"),
        )
    except TypeError:
        return None


def _parse_task_plan(payload: object) -> list[DaemonTaskPlanItem]:
    if not isinstance(payload, list):
        return []

    items: list[DaemonTaskPlanItem] = []
    for raw_item in payload:
        item = _parse_task_plan_item(raw_item)
        if item is not None:
            items.append(item)
    return items


def _parse_current_task(payload: object) -> DaemonCurrentTask | None:
    if not isinstance(payload, dict):
        return None

    try:
        return DaemonCurrentTask(
            index=_expect_int(payload, "index"),
            label=_expect_str(payload, "label"),
            status=_expect_str(payload, "status"),
            description=_expect_optional_str(payload, "description"),
            notes=_expect_optional_str(payload, "notes"),
        )
    except TypeError:
        return None


def _parse_task_projection(payload: object) -> DaemonTaskProjection | None:
    if not isinstance(payload, dict):
        return None

    task_plan_payload = payload.get("task_plan", payload.get("tasks"))
    try:
        goal = _expect_optional_str(payload, "goal")
    except TypeError:
        goal = None

    return DaemonTaskProjection(
        goal=goal,
        progress=_parse_task_progress(payload.get("progress")),
        task_plan=_parse_task_plan(task_plan_payload),
        current_task=_parse_current_task(payload.get("current_task")),
    )


def _parse_recent_activity_item(payload: object) -> DaemonRecentActivity | None:
    if not isinstance(payload, dict):
        return None

    try:
        return DaemonRecentActivity(
            kind=_expect_str(payload, "kind"),
            seq=_activity_optional_int(payload, "seq"),
            timestamp=_activity_optional_str(payload, "timestamp"),
            tool_name=_activity_optional_str(payload, "toolName"),
            turn_index=_activity_optional_int(payload, "turnIndex"),
            category=_activity_optional_str(payload, "category"),
            label=_activity_optional_str(payload, "label"),
            snippet=_activity_optional_str(payload, "snippet"),
            is_error=_activity_optional_bool(payload, "isError"),
            tool_count=_activity_optional_int(payload, "toolCount"),
        )
    except TypeError:
        return None


def _parse_recent_activity(payload: object) -> list[DaemonRecentActivity] | None:
    if payload is None:
        return None
    if not isinstance(payload, list):
        return []

    items: list[DaemonRecentActivity] = []
    for raw_item in payload:
        item = _parse_recent_activity_item(raw_item)
        if item is not None:
            items.append(item)
    return items


def _parse_message_item(payload: object) -> DaemonAgentMessage | None:
    if not isinstance(payload, dict):
        return None

    try:
        return DaemonAgentMessage(
            kind=_expect_str(payload, "kind"),
            seq=_expect_optional_int(payload, "seq"),
            timestamp=_expect_optional_str(payload, "timestamp"),
            label=_expect_optional_str(payload, "label"),
            text=_expect_str(payload, "text"),
        )
    except TypeError:
        return None


def _parse_messages_payload(payload: object) -> DaemonAgentMessagesOk:
    if not isinstance(payload, dict):
        raise TypeError

    messages_payload = payload.get("messages")
    if not isinstance(messages_payload, list):
        raise TypeError

    messages = [_parse_message_item(raw_message) for raw_message in messages_payload]
    if any(message is None for message in messages):
        raise TypeError

    return DaemonAgentMessagesOk(
        root_id=_expect_str(payload, "root_id"),
        agent_handle=_expect_str(payload, "agent_handle"),
        messages=[message for message in messages if message is not None],
    )


def _parse_payload(payload: object) -> DaemonSummaryOk:
    if not isinstance(payload, dict):
        raise TypeError

    counts_payload = payload.get("counts")
    if not isinstance(counts_payload, dict):
        raise TypeError

    agents_payload = payload.get("agents")
    if not isinstance(agents_payload, list):
        raise TypeError

    counts = DaemonSummaryCounts(
        pending=_expect_int(counts_payload, "pending"),
        running=_expect_int(counts_payload, "running"),
        completed=_expect_int(counts_payload, "completed"),
        failed=_expect_int(counts_payload, "failed"),
        total=_expect_int(counts_payload, "total"),
    )

    agents = [
        DaemonSummaryAgent(
            agent_handle=_expect_str(raw_agent, "agent_handle"),
            agent_type=_expect_optional_str(raw_agent, "agent_type"),
            role=_expect_str(raw_agent, "role"),
            session_name=_expect_str(raw_agent, "session_name"),
            status=_expect_str(raw_agent, "status"),
            result_preview=_expect_optional_str(raw_agent, "result_preview"),
            error_preview=_expect_optional_str(raw_agent, "error_preview"),
            exit_code=_expect_optional_int(raw_agent, "exit_code"),
            created_at=_expect_optional_str(raw_agent, "created_at"),
            started_at=_expect_optional_str(raw_agent, "started_at"),
            ended_at=_expect_optional_str(raw_agent, "ended_at"),
            agent_id_short=_expect_optional_str(raw_agent, "agent_id_short"),
            model=_expect_optional_str(raw_agent, "model"),
            task=_parse_task_projection(raw_agent.get("task")),
            recent_activity=_parse_recent_activity(raw_agent.get("recent_activity")),
        )
        for raw_agent in agents_payload
        if isinstance(raw_agent, dict)
    ]

    if len(agents) != len(agents_payload):
        raise TypeError

    return DaemonSummaryOk(
        root_id=_expect_str(payload, "root_id"),
        counts=counts,
        agents=agents,
        session_active=_expect_bool(payload, "session_active"),
    )


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
