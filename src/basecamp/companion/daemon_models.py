"""Dataclass models for daemon Swarm observability payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
class DaemonSkillInvocation:
    """One skill invocation aggregate from a daemon projection."""

    name: str
    count: int
    last_seq: int | None = None
    last_timestamp: str | None = None


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
    skills: list[DaemonSkillInvocation] | None = None


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
