"""Payload parsing for daemon Swarm observability responses."""

from __future__ import annotations

from typing import Any

from basecamp.companion.daemon.models import (
    DaemonAgentMessage,
    DaemonAgentMessagesOk,
    DaemonCurrentTask,
    DaemonRecentActivity,
    DaemonSkillInvocation,
    DaemonSummaryAgent,
    DaemonSummaryCounts,
    DaemonSummaryOk,
    DaemonTaskPlanItem,
    DaemonTaskProgress,
    DaemonTaskProjection,
)


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


def _parse_skill_item(payload: object) -> DaemonSkillInvocation | None:
    if not isinstance(payload, dict):
        return None

    try:
        return DaemonSkillInvocation(
            name=_expect_str(payload, "name"),
            count=_expect_int(payload, "count"),
            last_seq=_activity_optional_int(payload, "last_seq"),
            last_timestamp=_activity_optional_str(payload, "last_timestamp"),
        )
    except TypeError:
        return None


def _parse_skills(payload: object) -> list[DaemonSkillInvocation] | None:
    if payload is None:
        return None
    if not isinstance(payload, list):
        return []

    items: list[DaemonSkillInvocation] = []
    for raw_item in payload:
        item = _parse_skill_item(raw_item)
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
            skills=_parse_skills(raw_agent.get("skills")),
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
