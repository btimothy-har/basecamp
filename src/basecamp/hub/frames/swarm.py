"""Agent-swarm protocol frames.

Dispatch, telemetry, results, waits, agent listing, peer messaging, cancellation,
and workstream lifecycle — the frames that coordinate the agent swarm.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .version import ProtocolFrame


class DispatchSpec(BaseModel):
    """Run launch specification."""

    argv: list[str]
    env: dict[str, str]
    cwd: str
    resume_path: str | None
    fork_from: str | None = None
    task: str
    # Every dispatched run owns a workspace; the reaper removes it at run end. Deliverable
    # (worker) runs additionally carry branch fields; report/ask runs pass owned_branch=None.
    # The branch is durable except when this run minted it (branch_created) and has zero
    # commits ahead of branch_base — then it is deleted too (nothing happened).
    owned_worktree: str | None = None
    owned_branch: str | None = None
    branch_base: str | None = None
    branch_created: bool = False


class DispatchFrame(ProtocolFrame):
    """Dispatch request frame."""

    type: Literal["dispatch"]
    run_id: str
    agent_id: str | None = None
    agent_handle: str | None = None
    agent_type: str | None = None
    model: str | None = None
    spec: DispatchSpec


class DispatchAckFrame(ProtocolFrame):
    """Dispatch acknowledgement frame."""

    type: Literal["dispatch_ack"]
    run_id: str
    status: Literal["spawned", "rejected"]
    reason: str | None = None


class TelemetryFrame(ProtocolFrame):
    """Telemetry frame from an agent."""

    type: Literal["telemetry"]
    run_id: str
    agent_id: str
    report_token: str
    kind: str
    payload: dict[str, Any]


class ResultReportFrame(ProtocolFrame):
    """Terminal result-report frame."""

    type: Literal["result_report"]
    run_id: str
    agent_id: str
    report_token: str
    status: Literal["ok", "error"]
    result: str | None
    error: str | None
    usage: dict[str, Any] | None


class WaitFrame(ProtocolFrame):
    """Wait request frame."""

    type: Literal["wait"]
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


class WaitResultFrame(ProtocolFrame):
    """Wait response frame."""

    type: Literal["wait_result"]
    results: list[WaitResultItem]


class ListAgentsFrame(ProtocolFrame):
    """Request list of agents in requester root scope."""

    type: Literal["list_agents"]
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


class ListAgentsResultFrame(ProtocolFrame):
    """List-agents response frame."""

    type: Literal["list_agents_result"]
    request_id: str
    agents: list[ListAgentItem]


class PeerMessageFrame(ProtocolFrame):
    """Request asynchronous delivery of a peer message."""

    type: Literal["peer_message"]
    request_id: str
    target_handle: str
    message: str
    interrupt: bool = False


class PeerMessageAckFrame(ProtocolFrame):
    """Acceptance acknowledgement for a peer message request."""

    type: Literal["peer_message_ack"]
    request_id: str
    message_id: str | None
    status: Literal["accepted", "unknown"]
    error: str | None = None


PeerMessageRelation = Literal["self", "parent", "ancestor", "child", "descendant", "peer", "unknown"]


class PeerMessageDeliveryFrame(ProtocolFrame):
    """Peer message delivery from daemon to recipient agent."""

    type: Literal["peer_message_delivery"]
    message_id: str
    from_handle: str | None
    from_relation: PeerMessageRelation
    from_product_role: str | None = None
    message: str
    interrupt: bool


class PeerMessageDeliveryAckFrame(ProtocolFrame):
    """Recipient acknowledgement that a peer message delivery was queued."""

    type: Literal["peer_message_delivery_ack"]
    message_id: str
    status: Literal["queued", "failed"]
    error: str | None = None


class MessageStatusFrame(ProtocolFrame):
    """Request delivery lifecycle status for a peer message."""

    type: Literal["message_status"]
    request_id: str
    message_id: str
    wait_until_delivery: bool = False
    timeout_s: float | None = None


class MessageStatusResultFrame(ProtocolFrame):
    """Delivery lifecycle status for a peer message."""

    type: Literal["message_status_result"]
    request_id: str
    message_id: str
    status: Literal["accepted", "sent", "queued", "failed", "unavailable", "unknown"]
    error: str | None = None
    created_at: str | None
    sent_at: str | None
    queued_at: str | None
    failed_at: str | None


class CancelFrame(ProtocolFrame):
    """Request cancellation of an agent's current run."""

    type: Literal["cancel"]
    request_id: str
    target_handle: str


class CancelAckFrame(ProtocolFrame):
    """Acknowledgement for a cancel request."""

    type: Literal["cancel_ack"]
    request_id: str
    status: Literal["cancelled", "not_found", "not_authorized", "already_terminal"]
    error: str | None = None


class CreateWorkstreamFrame(ProtocolFrame):
    """Request to create a workstream."""

    type: Literal["create_workstream"]
    request_id: str
    workstream_id: str
    slug: str
    label: str
    brief: str
    source_dossier_path: str
    constraints: str | None = None
    source_repo_page_path: str | None = None


class CreateWorkstreamAckFrame(ProtocolFrame):
    """Acknowledgement for a create-workstream request."""

    type: Literal["create_workstream_ack"]
    request_id: str
    status: Literal["created", "slug_conflict", "error"]
    workstream_id: str | None = None
    slug: str | None = None
    error: str | None = None


class AttachWorkstreamAgentFrame(ProtocolFrame):
    """Request to attach the requester's own node to a workstream."""

    type: Literal["attach_workstream_agent"]
    request_id: str
    workstream: str
    repo: str | None = None
    worktree_label: str | None = None
    status: str = "attached"
    error: str | None = None


class AttachWorkstreamAgentAckFrame(ProtocolFrame):
    """Acknowledgement for an attach-workstream-agent request."""

    type: Literal["attach_workstream_agent_ack"]
    request_id: str
    status: Literal["attached", "not_found", "error"]
    error: str | None = None


class UpdateWorkstreamFrame(ProtocolFrame):
    """Request to update a workstream's status."""

    type: Literal["update_workstream"]
    request_id: str
    workstream: str
    status: Literal["open", "closed"]


class UpdateWorkstreamAckFrame(ProtocolFrame):
    """Acknowledgement for an update-workstream request."""

    type: Literal["update_workstream_ack"]
    request_id: str
    status: Literal["updated", "not_found", "invalid_status", "error"]
    error: str | None = None


class ReviseWorkstreamFrame(ProtocolFrame):
    """Request to revise a workstream's content, retaining the prior version."""

    type: Literal["revise_workstream"]
    request_id: str
    workstream: str
    label: str
    brief: str
    constraints: str | None = None


class ReviseWorkstreamAckFrame(ProtocolFrame):
    """Acknowledgement for a revise-workstream request, carrying the new version."""

    type: Literal["revise_workstream_ack"]
    request_id: str
    status: Literal["revised", "not_found", "error"]
    version: int | None = None
    error: str | None = None
