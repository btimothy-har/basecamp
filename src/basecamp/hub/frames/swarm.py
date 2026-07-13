"""Agent-swarm protocol frames.

Dispatch, telemetry, results, waits, agent listing, peer messaging, cancellation,
and workstream lifecycle — the frames that coordinate the agent swarm.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .version import PROTOCOL_VERSION


class DispatchSpec(BaseModel):
    """Run launch specification."""

    argv: list[str]
    env: dict[str, str]
    cwd: str
    resume_path: str | None
    fork_from: str | None = None
    task: str


class DispatchFrame(BaseModel):
    """Dispatch request frame."""

    type: Literal["dispatch"]
    v: Literal[PROTOCOL_VERSION]
    run_id: str
    agent_id: str | None = None
    agent_handle: str | None = None
    agent_type: str | None = None
    model: str | None = None
    spec: DispatchSpec


class DispatchAckFrame(BaseModel):
    """Dispatch acknowledgement frame."""

    type: Literal["dispatch_ack"]
    v: Literal[PROTOCOL_VERSION]
    run_id: str
    status: Literal["spawned", "rejected"]
    reason: str | None = None


class TelemetryFrame(BaseModel):
    """Telemetry frame from an agent."""

    type: Literal["telemetry"]
    v: Literal[PROTOCOL_VERSION]
    run_id: str
    agent_id: str
    report_token: str
    kind: str
    payload: dict[str, Any]


class ResultReportFrame(BaseModel):
    """Terminal result-report frame."""

    type: Literal["result_report"]
    v: Literal[PROTOCOL_VERSION]
    run_id: str
    agent_id: str
    report_token: str
    status: Literal["ok", "error"]
    result: str | None
    error: str | None
    usage: dict[str, Any] | None


class WaitFrame(BaseModel):
    """Wait request frame."""

    type: Literal["wait"]
    v: Literal[PROTOCOL_VERSION]
    agent_ids: list[str] = Field(default_factory=list)
    agent_handles: list[str] = Field(default_factory=list)
    mode: Literal["all"]
    timeout_s: float


class WaitResultItem(BaseModel):
    """Single wait result item."""

    agent_id: str | None = None
    agent_handle: str | None = None
    status: Literal["completed", "failed", "running", "unknown"]
    result: str | None = None
    error: str | None = None


class WaitResultFrame(BaseModel):
    """Wait response frame."""

    type: Literal["wait_result"]
    v: Literal[PROTOCOL_VERSION]
    results: list[WaitResultItem]


class ListAgentsFrame(BaseModel):
    """Request list of agents in requester root scope."""

    type: Literal["list_agents"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    awaitable: bool = False


class ListAgentItem(BaseModel):
    """Single list-agents row."""

    agent_id: str
    agent_handle: str | None = None
    agent_type: str | None = None
    parent_id: str | None
    role: str
    session_name: str
    depth: int
    status: Literal["pending", "running", "completed", "failed", "idle"]
    awaitable: bool
    task: str | None = None


class ListAgentsResultFrame(BaseModel):
    """List-agents response frame."""

    type: Literal["list_agents_result"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    agents: list[ListAgentItem]


class PeerMessageFrame(BaseModel):
    """Request asynchronous delivery of a peer message."""

    type: Literal["peer_message"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    target_handle: str
    message: str
    interrupt: bool = False


class PeerMessageAckFrame(BaseModel):
    """Acceptance acknowledgement for a peer message request."""

    type: Literal["peer_message_ack"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    message_id: str | None
    status: Literal["accepted", "unknown"]
    error: str | None = None


PeerMessageRelation = Literal["self", "parent", "ancestor", "child", "descendant", "peer", "unknown"]


class PeerMessageDeliveryFrame(BaseModel):
    """Peer message delivery from daemon to recipient agent."""

    type: Literal["peer_message_delivery"]
    v: Literal[PROTOCOL_VERSION]
    message_id: str
    from_handle: str | None
    from_relation: PeerMessageRelation
    from_product_role: str | None = None
    message: str
    interrupt: bool


class PeerMessageDeliveryAckFrame(BaseModel):
    """Recipient acknowledgement that a peer message delivery was queued."""

    type: Literal["peer_message_delivery_ack"]
    v: Literal[PROTOCOL_VERSION]
    message_id: str
    status: Literal["queued", "failed"]
    error: str | None = None


class MessageStatusFrame(BaseModel):
    """Request delivery lifecycle status for a peer message."""

    type: Literal["message_status"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    message_id: str
    wait_until_delivery: bool = False
    timeout_s: float | None = None


class MessageStatusResultFrame(BaseModel):
    """Delivery lifecycle status for a peer message."""

    type: Literal["message_status_result"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    message_id: str
    status: Literal["accepted", "sent", "queued", "failed", "unavailable", "unknown"]
    error: str | None = None
    created_at: str | None
    sent_at: str | None
    queued_at: str | None
    failed_at: str | None


class CancelFrame(BaseModel):
    """Request cancellation of an agent's current run."""

    type: Literal["cancel"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    target_handle: str


class CancelAckFrame(BaseModel):
    """Acknowledgement for a cancel request."""

    type: Literal["cancel_ack"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    status: Literal["cancelled", "not_found", "not_authorized", "already_terminal"]
    error: str | None = None


class CreateWorkstreamFrame(BaseModel):
    """Request to create a workstream."""

    type: Literal["create_workstream"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    workstream_id: str
    slug: str
    label: str
    brief: str
    source_dossier_path: str
    constraints: str | None = None
    source_repo_page_path: str | None = None


class CreateWorkstreamAckFrame(BaseModel):
    """Acknowledgement for a create-workstream request."""

    type: Literal["create_workstream_ack"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    status: Literal["created", "slug_conflict", "error"]
    workstream_id: str | None = None
    slug: str | None = None
    error: str | None = None


class AttachWorkstreamAgentFrame(BaseModel):
    """Request to attach the requester's own node to a workstream."""

    type: Literal["attach_workstream_agent"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    workstream: str
    repo: str | None = None
    worktree_label: str | None = None
    status: str = "attached"
    error: str | None = None


class AttachWorkstreamAgentAckFrame(BaseModel):
    """Acknowledgement for an attach-workstream-agent request."""

    type: Literal["attach_workstream_agent_ack"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    status: Literal["attached", "not_found", "error"]
    error: str | None = None


class UpdateWorkstreamFrame(BaseModel):
    """Request to update a workstream's status."""

    type: Literal["update_workstream"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    workstream: str
    status: Literal["open", "closed"]


class UpdateWorkstreamAckFrame(BaseModel):
    """Acknowledgement for an update-workstream request."""

    type: Literal["update_workstream_ack"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    status: Literal["updated", "not_found", "invalid_status", "error"]
    error: str | None = None


class ReviseWorkstreamFrame(BaseModel):
    """Request to revise a workstream's content, retaining the prior version."""

    type: Literal["revise_workstream"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    workstream: str
    label: str
    brief: str
    constraints: str | None = None


class ReviseWorkstreamAckFrame(BaseModel):
    """Acknowledgement for a revise-workstream request, carrying the new version."""

    type: Literal["revise_workstream_ack"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    status: Literal["revised", "not_found", "error"]
    version: int | None = None
    error: str | None = None
